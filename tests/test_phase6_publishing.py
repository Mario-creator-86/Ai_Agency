"""Phase 6 Autonomous Publishing & Distribution test suite.

Tests:
- Channel seeding and configuration (Channel A Main Factual, Channel B Office Serial).
- 5-point Publishing Gate evaluation (Autonomy, File Existence, QC PASSED, Factual Claims, Duplicate Protection).
- Idempotency guarantees: unique (channel_id, idempotency_key) prevents duplicate uploads.
- Deterministic publishing flow: intent -> gate validation -> private upload -> remote ID/URL.
- Remote reconciliation from REMOTE_UNKNOWN / FAILED_RETRYABLE.
- REST API routes under /api/v1/publishing with Owner token authentication.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.factual.models import FactualClaim, ScriptDraft, TopicIdea
from app.media.models import MediaAsset, QualityControlReport, Storyboard, VideoRenderJob
from app.models import OwnerPolicy
from app.providers.deterministic_pub import DeterministicPublishingAdapter
from app.publishing.models import ChannelRecord, PublicationRecord
from app.publishing.services import (
    PublishingGateError,
    configure_channel,
    create_publication_intent,
    evaluate_publishing_gate,
    execute_publication,
    get_channel,
    get_publication,
    list_channels,
    list_publications,
    publish_media_asset,
    reconcile_publication,
    seed_default_channels,
)
from app.services import utc_now


def _create_verified_asset_bundle(engine, tmp_path, *, qc_passed: bool = True, refuted_claim: bool = False):
    """Helper to create topic, claim, script, storyboard, render job, media asset on disk, and QC report."""
    now = utc_now()
    topic_id = str(uuid4())
    claim_id = str(uuid4())
    script_id = str(uuid4())
    sb_id = str(uuid4())
    job_id = str(uuid4())
    asset_id = str(uuid4())
    qc_id = str(uuid4())

    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    video_file = media_dir / f"{asset_id}.mp4"
    video_file.write_bytes(b"Simulated MP4 video bytes for YouTube Shorts publication")

    # 1. Clear autonomy stop so tests can proceed
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        if policy:
            policy.autonomy_stopped = False

    # 2. Commit Factual records
    with Session(engine) as session, session.begin():
        topic = TopicIdea(
            id=topic_id,
            title="JWST Infrared Space Discoveries",
            topic="Space Exploration",
            angle="Early galaxy formation",
            target_audience="science_enthusiasts",
            novelty_score=0.95,
            status="SELECTED",
            created_at=now,
        )
        session.add(topic)

        claim = FactualClaim(
            id=claim_id,
            topic_id=topic_id,
            claim_text="JWST observes in the infrared spectrum.",
            claim_type="PHYSICAL_MEASUREMENT",
            importance="CORE",
            status="REFUTED" if refuted_claim else "SUPPORTED",
            confidence=0.98,
            created_at=now,
        )
        session.add(claim)

        script = ScriptDraft(
            id=script_id,
            topic_id=topic_id,
            version=1,
            title="JWST Infrared Vision",
            target_duration_seconds=15,
            voiceover_full_text="JWST observes the universe in infrared.",
            scenes_json=[{
                "scene_index": 1,
                "visual_prompt": "Infrared cosmic view",
                "duration_seconds": 15.0,
                "voiceover_segment": "JWST observes the universe in infrared.",
                "shot_type": "WIDE",
                "transition_in": "FADE",
                "claim_ids": [claim_id],
            }],
            status="APPROVED",
            claim_ids_json=[claim_id],
            unverified_claim_ids_json=[],
            created_at=now,
        )
        session.add(script)

    # 3. Commit Storyboard & Media records
    with Session(engine) as session, session.begin():
        sb = Storyboard(
            id=sb_id,
            script_draft_id=script_id,
            title="JWST Infrared Vision Storyboard",
            visual_style="MOTION_GRAPHIC",
            aspect_ratio="9:16",
            target_duration_seconds=15,
            status="APPROVED",
            total_scenes=1,
            created_at=now,
        )
        session.add(sb)

        asset = MediaAsset(
            id=asset_id,
            asset_type="VIDEO_COMPOSED",
            uri_or_path=str(video_file),
            file_size_bytes=video_file.stat().st_size,
            mime_type="video/mp4",
            width=1080,
            height=1920,
            duration_seconds=15.0,
            provider_name="deterministic_assembler",
            license_status="OWNED_INTERNAL",
            provenance_hash=sha256(video_file.read_bytes()).hexdigest(),
            created_at=now,
        )
        session.add(asset)

        job = VideoRenderJob(
            id=job_id,
            storyboard_id=sb_id,
            output_asset_id=asset_id,
            status="COMPLETED",
            render_engine="opencv_deterministic",
            command_args_json={},
            started_at=now,
            finished_at=now,
        )
        session.add(job)

        qc = QualityControlReport(
            id=qc_id,
            media_asset_id=asset_id,
            status="PASSED" if qc_passed else "FAILED",
            score=0.96 if qc_passed else 0.40,
            checks_json={"technical": {"passed": qc_passed}, "factual": {"passed": not refuted_claim}},
            failure_reasons_json=[] if (qc_passed and not refuted_claim) else ["QC test failure"],
            verified_at=now,
        )
        session.add(qc)

    return {
        "asset_id": asset_id,
        "video_file": video_file,
        "claim_id": claim_id,
        "script_id": script_id,
    }


def test_channel_seeding_and_configuration(engine):
    # 1. Seed defaults
    seeded = seed_default_channels(engine)
    assert seeded == 2

    # 2. Verify seeded channels
    channels = list_channels(engine)
    assert len(channels) == 2
    types = [c["channel_type"] for c in channels]
    assert "MAIN_FACTUAL" in types
    assert "OFFICE_SERIAL" in types

    ch_a = next(c for c in channels if c["channel_type"] == "MAIN_FACTUAL")
    assert ch_a["upload_privacy_default"] == "private"
    assert ch_a["platform"] == "YOUTUBE"

    # 3. Re-seeding is idempotent
    assert seed_default_channels(engine) == 0

    # 4. Configure channel
    updated = configure_channel(
        engine,
        channel_id=ch_a["id"],
        channel_name="Main Channel A - Renamed",
        remote_channel_id="UC_custom_youtube_id",
        credentials_ref="credentials_vault_key_1",
        upload_privacy_default="private",
        correlation_id=str(uuid4()),
    )
    assert updated["channel_name"] == "Main Channel A - Renamed"
    assert updated["remote_channel_id"] == "UC_custom_youtube_id"
    assert updated["status"] == "AUTHENTICATED"


def test_publishing_gate_evaluations(engine, tmp_path):
    seed_default_channels(engine)
    channels = list_channels(engine)
    ch_id = channels[0]["id"]

    # 1. Rejection when MediaAsset does not exist
    eval_missing = evaluate_publishing_gate(engine, "non-existent-asset", ch_id)
    assert eval_missing["eligible"] is False
    assert any("not found" in c["detail"] for c in eval_missing["checks"])

    # 2. Rejection when QC Report is FAILED
    bundle_qc_failed = _create_verified_asset_bundle(engine, tmp_path, qc_passed=False)
    eval_qc_fail = evaluate_publishing_gate(engine, bundle_qc_failed["asset_id"], ch_id)
    assert eval_qc_fail["eligible"] is False
    assert any("QC Report is FAILED" in c["detail"] for c in eval_qc_fail["checks"])

    # 3. Rejection when Factual Claim is REFUTED
    bundle_refuted = _create_verified_asset_bundle(engine, tmp_path, qc_passed=True, refuted_claim=True)
    eval_refuted = evaluate_publishing_gate(engine, bundle_refuted["asset_id"], ch_id)
    assert eval_refuted["eligible"] is False
    assert any("unverified/refuted claims" in c["detail"] for c in eval_refuted["checks"])

    # 4. Rejection when Global Autonomy Stop is Active
    bundle_valid = _create_verified_asset_bundle(engine, tmp_path, qc_passed=True)
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_stopped = True

    eval_stopped = evaluate_publishing_gate(engine, bundle_valid["asset_id"], ch_id)
    assert eval_stopped["eligible"] is False
    assert any(c["check_name"] == "AUTONOMY_GATE" and not c["passed"] for c in eval_stopped["checks"])

    # Clear stop
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_stopped = False

    # 5. Success when all 5 checks pass
    eval_ok = evaluate_publishing_gate(engine, bundle_valid["asset_id"], ch_id)
    assert eval_ok["eligible"] is True
    assert len(eval_ok["reasons"]) == 0
    assert all(c["passed"] for c in eval_ok["checks"])


def test_idempotency_and_duplicate_prevention(engine, tmp_path):
    seed_default_channels(engine)
    channels = list_channels(engine)
    ch_id = channels[0]["id"]
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    asset_id = bundle["asset_id"]
    idem_key = f"idem_{uuid4()}"

    # First intent creation
    intent1 = create_publication_intent(
        engine,
        channel_id=ch_id,
        media_asset_id=asset_id,
        title="Test YouTube Short",
        description="A short about space",
        tags=["#shorts", "space"],
        privacy_status="private",
        idempotency_key=idem_key,
        correlation_id=str(uuid4()),
    )
    assert intent1["idempotency_key"] == idem_key
    assert intent1["status"] == "VALIDATED"

    # Second intent creation with same (channel_id, idempotency_key) returns existing record
    intent2 = create_publication_intent(
        engine,
        channel_id=ch_id,
        media_asset_id=asset_id,
        title="Test YouTube Short Duplicate",
        description="Different description",
        tags=[],
        privacy_status="private",
        idempotency_key=idem_key,
        correlation_id=str(uuid4()),
    )
    assert intent2["id"] == intent1["id"]
    assert intent2["title"] == intent1["title"]


def test_end_to_end_publishing_flow(engine, tmp_path):
    seed_default_channels(engine)
    channels = list_channels(engine)
    ch_id = channels[0]["id"]
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    asset_id = bundle["asset_id"]

    adapter = DeterministicPublishingAdapter()

    # High-level publish_media_asset helper
    pub = publish_media_asset(
        engine,
        media_asset_id=asset_id,
        channel_id=ch_id,
        title="JWST Deep Field Discovery #Shorts",
        description="Exploring early galaxies through infrared optics. #space #science",
        tags=["#shorts", "space", "astronomy"],
        privacy_status="private",
        correlation_id=str(uuid4()),
        provider=adapter,
    )

    # The deterministic adapter is a simulator: the record must say so and must not carry a
    # YouTube URL, otherwise the UI would present a video that does not exist.
    assert pub["status"] == "PUBLISHED_SIMULATED"
    assert pub["privacy_status"] == "private"
    assert pub["remote_video_id"].startswith("sim:")
    assert pub["remote_url"] is None
    assert "Simulated upload" in (pub["error_detail"] or "")
    assert pub["published_at"] is not None

    # Gate duplicate check: attempting to publish again must fail gate
    with pytest.raises(PublishingGateError) as exc_info:
        publish_media_asset(
            engine,
            media_asset_id=asset_id,
            channel_id=ch_id,
            title="Second Attempt",
            description="desc",
            tags=[],
            privacy_status="private",
            correlation_id=str(uuid4()),
            provider=adapter,
        )
    assert "Duplicate publishing prevented" in str(exc_info.value)


def test_reconciliation_from_remote_unknown(engine, tmp_path):
    seed_default_channels(engine)
    channels = list_channels(engine)
    ch_id = channels[0]["id"]
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    asset_id = bundle["asset_id"]

    adapter = DeterministicPublishingAdapter()

    # Create intent
    pub = create_publication_intent(
        engine,
        channel_id=ch_id,
        media_asset_id=asset_id,
        title="Reconciliation Test Video",
        description="Testing recovery from ambiguous network timeout",
        tags=["#test"],
        privacy_status="private",
        idempotency_key=str(uuid4()),
        correlation_id=str(uuid4()),
    )

    # Simulate ambiguous timeout during upload: state becomes REMOTE_UNKNOWN
    with Session(engine) as session, session.begin():
        rec = session.get(PublicationRecord, pub["id"])
        rec.status = "REMOTE_UNKNOWN"
        rec.remote_video_id = "sim_yt_rec_001"

    # Pre-register video on adapter so reconciliation finds it
    adapter._published_videos["sim_yt_rec_001"] = {
        "remote_video_id": "sim_yt_rec_001",
        "title": "Reconciliation Test Video",
        "privacy_status": "private",
        "status": "PUBLISHED",
        "remote_url": "https://youtube.com/shorts/sim_yt_rec_001",
    }

    # Call reconcile
    reconciled = reconcile_publication(
        engine,
        publication_id=pub["id"],
        provider=adapter,
        correlation_id=str(uuid4()),
    )
    assert reconciled["status"] == "PUBLISHED_SIMULATED"
    assert reconciled["remote_video_id"] == "sim_yt_rec_001"
    assert reconciled["published_at"] is not None


def test_publishing_api_endpoints_with_owner_auth(client, headers, engine, tmp_path):
    # 1. Unauthenticated request rejected
    res = client.get("/api/v1/publishing/channels")
    assert res.status_code == 401

    # 2. A GET must not mutate state: the listing starts empty until seeding is commanded.
    res = client.get("/api/v1/publishing/channels", headers=headers)
    assert res.status_code == 200
    assert res.json()["channels"] == []
    assert res.json()["publisher_configured"] is False

    res = client.post("/api/v1/publishing/channels/seed", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data["channels"]) >= 2
    # Seeded slots are not configured channels: no invented remote ID, no CONFIGURED status.
    for ch in data["channels"]:
        assert ch["status"] == "NOT_CONFIGURED"
        assert ch["remote_channel_id"] is None
    channel_id = data["channels"][0]["id"]

    # 3. Authenticated publications listing
    res = client.get("/api/v1/publishing/publications", headers=headers)
    assert res.status_code == 200
    assert "publications" in res.json()

    # 4. Evaluate Gate API
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    res = client.get(
        f"/api/v1/publishing/gate/evaluate/{bundle['asset_id']}/{channel_id}",
        headers=headers,
    )
    assert res.status_code == 200
    gate_data = res.json()
    assert gate_data["eligible"] is True
    assert len(gate_data["checks"]) == 5

    # 5. Without real YouTube credentials the API must refuse to publish. It must never
    #    silently substitute the simulator and report a publication that does not exist.
    res = client.post(
        f"/api/v1/publishing/publish-asset/{bundle['asset_id']}",
        headers=headers,
    )
    assert res.status_code == 503
    detail = res.json()["detail"]
    assert detail["error"] == "PublisherNotConfigured"
    assert "STUDIO_YOUTUBE_CLIENT_ID" in detail["required_settings"]

    # Nothing was recorded as published.
    res = client.get("/api/v1/publishing/publications", headers=headers)
    assert all(p["status"] != "PUBLISHED" for p in res.json()["publications"])

    # 6. With a provider injected (tests only), the run is recorded as SIMULATED and the
    #    channel must still be authenticated first.
    inner_app = client.app.app  # TrustedHostMiddleware wraps the FastAPI application
    inner_app.state.publishing_provider = DeterministicPublishingAdapter()
    try:
        res = client.post(
            f"/api/v1/publishing/publish-asset/{bundle['asset_id']}",
            headers=headers,
        )
        assert res.status_code == 409
        assert res.json()["detail"]["error"] == "ChannelNotAuthenticated"

        configure_channel(
            engine,
            channel_id,
            None,
            "UCrealchannelid0000000",
            "owner-oauth-ref",
            "private",
            str(uuid4()),
        )
        assert get_channel(engine, channel_id)["status"] == "AUTHENTICATED"

        res = client.post(
            f"/api/v1/publishing/publish-asset/{bundle['asset_id']}",
            headers=headers,
        )
        assert res.status_code in (200, 201)
        pub_data = res.json()
        assert pub_data["status"] == "PUBLISHED_SIMULATED"
        assert pub_data["remote_url"] is None
    finally:
        inner_app.state.publishing_provider = None

    # 7. Retrieve publication by ID
    res = client.get(f"/api/v1/publishing/publications/{pub_data['id']}", headers=headers)
    assert res.status_code == 200
    assert res.json()["id"] == pub_data["id"]
