"""Regression tests for the studio's truthfulness invariants.

Every test here locks in a rule that a previous implementation broke: the system must never
report configuration, publication, or quality that does not exist. These are governance
tests, not feature tests — if one of them fails, the product is lying to its Owner.

Covers:
- Channel slots are never seeded as configured, and never carry an invented remote channel ID.
- Publishing refuses to run without real credentials instead of falling back to a simulator.
- A simulated upload is never recorded as a real publication and never gets a youtube.com URL.
- A gate refusal is persisted with its event (auditable), not rolled back.
- QC measures the file: a non-video file named .mp4 cannot pass technical QC.
- A missing media asset is a clean rejection, not a database integrity error.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from app.media.models import MediaAsset, QualityControlReport
from app.media.qc import evaluate_media_qc
from app.models import DomainEvent, OwnerPolicy
from app.providers.deterministic_pub import DeterministicPublishingAdapter
from app.publishing.models import PublicationRecord
from app.publishing.services import (
    PublisherNotConfigured,
    PublishingAssetNotFound,
    PublishingGateError,
    create_publication_intent,
    derive_channel_status,
    execute_publication,
    list_channels,
    publish_media_asset,
    seed_default_channels,
)
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session


def _clear_stop(engine) -> None:
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        if policy:
            policy.autonomy_stopped = False


def _register_asset(engine, path: Path, *, provenance_hash: str | None = None) -> str:
    """Register a MediaAsset row pointing at an arbitrary file, as a renderer would."""
    import hashlib

    asset_id = str(uuid4())
    if provenance_hash is None:
        provenance_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "media.video_rendered", "media_asset", asset_id, 1, {}, str(uuid4())
        )
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=str(path),
                file_size_bytes=path.stat().st_size,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=18.0,
                provider_name="FFMPEG",
                remote_job_id=None,
                license_status="PROPRIETARY_STUDIO",
                provenance_hash=provenance_hash,
                created_at=utc_now(),
                event_id=event.event_id,
            )
        )
    return asset_id


def test_seeded_channels_are_not_reported_as_configured(engine):
    """A channel slot is not a configured channel: no invented ID, no CONFIGURED status."""
    assert seed_default_channels(engine) == 2
    channels = list_channels(engine)
    assert len(channels) == 2
    for channel in channels:
        assert channel["status"] == "NOT_CONFIGURED"
        assert channel["remote_channel_id"] is None
        assert channel["credentials_ref"] is None
        assert channel["last_sync_at"] is None


def test_channel_status_is_derived_from_what_actually_exists():
    assert derive_channel_status(None, None) == "NOT_CONFIGURED"
    assert derive_channel_status(None, "oauth-ref") == "NOT_CONFIGURED"
    assert derive_channel_status("UCrealid", None) == "AUTH_REQUIRED"
    assert derive_channel_status("UCrealid", "oauth-ref") == "AUTHENTICATED"


def test_publishing_without_a_provider_refuses_instead_of_simulating(engine, tmp_path):
    """No credentials must mean no publication, not a silent fallback to the simulator."""
    _clear_stop(engine)
    seed_default_channels(engine)
    channel_id = list_channels(engine)[0]["id"]
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00" * 2048)
    asset_id = _register_asset(engine, video)

    with pytest.raises(PublisherNotConfigured):
        publish_media_asset(
            engine,
            media_asset_id=asset_id,
            channel_id=channel_id,
            title="Should never publish",
            description="",
            tags=[],
        )


def test_simulated_upload_is_never_recorded_as_a_real_publication(engine, tmp_path):
    _clear_stop(engine)
    seed_default_channels(engine)
    channel_id = list_channels(engine)[0]["id"]
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00" * 2048)
    asset_id = _register_asset(engine, video)

    # Bypass QC for this test by writing a PASSED report directly; the point under test is
    # the recording of the upload result, not the gate.
    with Session(engine) as session, session.begin():
        event = append_event(
            session,
            "media.qc_evaluated",
            "quality_control_report",
            str(uuid4()),
            1,
            {},
            str(uuid4()),
        )
        session.add(
            QualityControlReport(
                id=str(uuid4()),
                media_asset_id=asset_id,
                status="PASSED",
                score=1.0,
                checks_json={},
                failure_reasons_json=[],
                verified_at=utc_now(),
                event_id=event.event_id,
            )
        )

    intent = create_publication_intent(
        engine, channel_id, asset_id, "Simulated run", "", [], "private", None, str(uuid4())
    )
    result = execute_publication(
        engine, DeterministicPublishingAdapter(), intent["id"], str(uuid4())
    )

    assert result["status"] == "PUBLISHED_SIMULATED"
    assert result["status"] != "PUBLISHED"
    assert result["remote_video_id"].startswith("sim:")
    assert result["remote_url"] is None
    assert "Simulated" in (result["error_detail"] or "")

    with Session(engine) as session:
        types = [e.event_type for e in session.scalars(select(DomainEvent)).all()]
    assert "publishing.video_published_simulated" in types
    assert "publishing.video_published" not in types


def test_simulated_adapter_never_returns_a_youtube_url(tmp_path):
    import asyncio

    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x01" * 1024)
    result = asyncio.run(
        DeterministicPublishingAdapter().upload_video(
            video, title="t", description="d", tags=[], privacy_status="private"
        )
    )
    assert result.simulated is True
    assert "youtube.com" not in (result.remote_url or "")
    assert result.remote_url == ""


def test_gate_refusal_is_persisted_and_auditable(engine, tmp_path):
    """A blocked publication is a governance decision and must survive as an audit record."""
    seed_default_channels(engine)
    channel_id = list_channels(engine)[0]["id"]
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00" * 1024)
    asset_id = _register_asset(engine, video)

    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = True

    with pytest.raises(PublishingGateError):
        create_publication_intent(
            engine, channel_id, asset_id, "Blocked run", "", [], "private", None, str(uuid4())
        )

    with Session(engine) as session:
        records = session.scalars(select(PublicationRecord)).all()
        assert len(records) == 1
        assert records[0].status == "BLOCKED_GATE"
        assert "autonomy stop" in (records[0].error_detail or "").lower()
        types = [e.event_type for e in session.scalars(select(DomainEvent)).all()]
    assert "publishing.gate_failed" in types


def test_missing_media_asset_is_a_clean_rejection(engine):
    seed_default_channels(engine)
    channel_id = list_channels(engine)[0]["id"]
    with pytest.raises(PublishingAssetNotFound):
        create_publication_intent(
            engine, channel_id, str(uuid4()), "No asset", "", [], "private", None, str(uuid4())
        )


def test_qc_rejects_a_non_video_file_named_mp4(engine, tmp_path):
    """The previous implementation trusted its own metadata; QC must measure the file."""
    import hashlib

    fake = tmp_path / "final_short_9_16.mp4"
    fake.write_bytes(b"\x00\x00\x00\x20ftypisom" + b'{"resolution": "1080x1920"}')
    asset_id = _register_asset(
        engine, fake, provenance_hash=hashlib.sha256(fake.read_bytes()).hexdigest()
    )

    report = evaluate_media_qc(engine, asset_id, str(uuid4()))

    assert report["status"] == "FAILED"
    assert report["checks_json"]["technical_qc"]["passed"] is False
    reasons = report["failure_reasons_json"]
    assert any("not a decodable video" in r or "ffprobe" in r for r in reasons)


def test_qc_rejects_a_tampered_provenance_hash(engine, tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00" * 4096)
    asset_id = _register_asset(engine, video, provenance_hash="0" * 64)

    report = evaluate_media_qc(engine, asset_id, str(uuid4()))

    assert report["checks_json"]["technical_qc"]["provenance_hash_verified"] is False
    assert report["status"] == "FAILED"


def test_character_drift_check_does_not_claim_to_pass(engine, tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00" * 4096)
    asset_id = _register_asset(engine, video)

    report = evaluate_media_qc(engine, asset_id, str(uuid4()))
    drift = report["checks_json"]["character_drift_qc"]

    assert drift["status"] == "NOT_IMPLEMENTED"
    assert drift["passed"] is None
