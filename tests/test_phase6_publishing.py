"""Phase 6 Autonomous Publishing & Distribution test suite.

Tests:
- Channel seeding and configuration (Channel A Main Factual, Channel B Office Serial).
- 5-point Publishing Gate evaluation (Autonomy, File Existence, QC PASSED,
  Factual Claims, Duplicate Protection).
- Idempotency guarantees: unique (channel_id, idempotency_key) prevents duplicate uploads.
- Deterministic publishing flow: intent -> gate validation -> private upload -> remote ID/URL.
- Remote reconciliation from REMOTE_UNKNOWN / FAILED_RETRYABLE.
- REST API routes under /api/v1/publishing with Owner token authentication.
"""

from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

import pytest
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
    film_identity,
    get_channel,
    list_channels,
    publish_media_asset,
    published_films,
    reconcile_publication,
    seed_default_channels,
)
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session


def _create_verified_asset_bundle(
    engine, tmp_path, *, qc_passed: bool = True, refuted_claim: bool = False
):
    """Helper to create topic, claim, script, storyboard, render job, media asset
    on disk, and QC report."""
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
            scenes_json=[
                {
                    "scene_index": 1,
                    "visual_prompt": "Infrared cosmic view",
                    "duration_seconds": 15.0,
                    "voiceover_segment": "JWST observes the universe in infrared.",
                    "shot_type": "WIDE",
                    "transition_in": "FADE",
                    "claim_ids": [claim_id],
                }
            ],
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
            checks_json={
                "technical": {"passed": qc_passed},
                "factual": {"passed": not refuted_claim},
            },
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
    assert updated["status"] == "CONFIGURED"


def test_publishing_gate_evaluations(engine, tmp_path):
    seed_default_channels(engine)
    channels = list_channels(engine)
    ch_id = channels[0]["id"]

    # 1. Rejection when MediaAsset does not exist
    eval_missing = evaluate_publishing_gate(engine, "non-existent-asset", ch_id)
    assert eval_missing["eligible"] is False
    assert any("nu există" in c["detail"] for c in eval_missing["checks"])

    # 2. Rejection when QC Report is FAILED
    bundle_qc_failed = _create_verified_asset_bundle(engine, tmp_path, qc_passed=False)
    eval_qc_fail = evaluate_publishing_gate(engine, bundle_qc_failed["asset_id"], ch_id)
    assert eval_qc_fail["eligible"] is False
    assert any(
        c["check_name"] == "QC_GATE" and c["data"]["qc_status"] == "FAILED"
        for c in eval_qc_fail["checks"]
    )
    assert "Controlul calității: nu a trecut" in eval_qc_fail["reasons"]

    # 3. Rejection when Factual Claim is REFUTED
    bundle_refuted = _create_verified_asset_bundle(
        engine, tmp_path, qc_passed=True, refuted_claim=True
    )
    eval_refuted = evaluate_publishing_gate(engine, bundle_refuted["asset_id"], ch_id)
    assert eval_refuted["eligible"] is False
    refuted_check = next(
        c for c in eval_refuted["checks"] if c["check_name"] == "FACTUAL_INTEGRITY_GATE"
    )
    assert refuted_check["passed"] is False
    assert refuted_check["data"]["unverified_claim_ids"] == [bundle_refuted["claim_id"]]

    # 4. Rejection when Global Autonomy Stop is Active
    bundle_valid = _create_verified_asset_bundle(engine, tmp_path, qc_passed=True)
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_stopped = True

    eval_stopped = evaluate_publishing_gate(engine, bundle_valid["asset_id"], ch_id)
    assert eval_stopped["eligible"] is False
    assert any(
        c["check_name"] == "AUTONOMY_GATE" and not c["passed"] for c in eval_stopped["checks"]
    )

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
    assert "Încărcare simulată" in (pub["error_detail"] or "")
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
    assert "Publicare dublă oprită" in str(exc_info.value)


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
        assert get_channel(engine, channel_id)["status"] == "CONFIGURED"
        # Simulated verified identity, only for this injected publishing-adapter test.
        with Session(engine) as session, session.begin():
            session.get(ChannelRecord, channel_id).status = "AUTHENTICATED"

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


# --------------------------------------------------------------------------------------------
# One film, many renders.
#
# Found live on 2026-09-12: the studio had rendered one storyboard four times and published
# the newest. The other three sat QC-PASSED in the queue and passed every gate, because the
# duplicate check compared `media_asset_id` — the FILE — and each render is a new file. The
# channel would have received the same video four days running. These tests describe identity
# as the film, which is what the audience actually sees.
# --------------------------------------------------------------------------------------------


def _another_render(engine, tmp_path, *, storyboard_id: str, script_id: str | None = None):
    """A second rendered file for a film that already has one.

    With ``script_id`` a second storyboard is written from the same script, which is the case
    a storyboard-only check would miss: two shot plans, one film.
    """
    now = utc_now()
    asset_id = str(uuid4())
    board_id = storyboard_id
    video_file = tmp_path / "media" / f"{asset_id}.mp4"
    video_file.parent.mkdir(parents=True, exist_ok=True)
    video_file.write_bytes(b"A second render of the same film, a different file entirely")

    with Session(engine) as session, session.begin():
        if script_id is not None:
            board_id = str(uuid4())
            session.add(
                Storyboard(
                    id=board_id,
                    script_draft_id=script_id,
                    title="Second storyboard, same script",
                    visual_style="MOTION_GRAPHIC",
                    aspect_ratio="9:16",
                    target_duration_seconds=15,
                    status="APPROVED",
                    total_scenes=1,
                    created_at=now,
                )
            )
        session.add(
            MediaAsset(
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
        )
        session.add(
            VideoRenderJob(
                id=str(uuid4()),
                storyboard_id=board_id,
                output_asset_id=asset_id,
                status="COMPLETED",
                render_engine="opencv_deterministic",
                command_args_json={},
                started_at=now,
                finished_at=now,
            )
        )
        session.add(
            QualityControlReport(
                id=str(uuid4()),
                media_asset_id=asset_id,
                status="PASSED",
                score=0.97,
                checks_json={"technical": {"passed": True}},
                failure_reasons_json=[],
                verified_at=now,
            )
        )
    return asset_id


def _storyboard_of(engine, asset_id: str) -> str:
    with Session(engine) as session:
        _, storyboard_id = film_identity(session, asset_id)
    assert storyboard_id is not None
    return storyboard_id


def test_film_identity_reads_the_script_behind_a_rendered_file(engine, tmp_path):
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    with Session(engine) as session:
        script_id, storyboard_id = film_identity(session, bundle["asset_id"])
        assert script_id == bundle["script_id"]
        assert storyboard_id is not None
        # A file nothing rendered has no film behind it, and that is said as "unknown" —
        # never as "new", which would let an unprovenanced file through as a first release.
        assert film_identity(session, str(uuid4())) == (None, None)


def test_a_second_render_of_a_published_film_is_refused_by_the_gate(engine, tmp_path):
    seed_default_channels(engine)
    ch_id = list_channels(engine)[0]["id"]
    bundle = _create_verified_asset_bundle(engine, tmp_path)

    published = publish_media_asset(
        engine,
        media_asset_id=bundle["asset_id"],
        channel_id=ch_id,
        title="JWST Deep Field Discovery",
        description="Exploring early galaxies.",
        tags=["#shorts"],
        privacy_status="private",
        correlation_id=str(uuid4()),
        provider=DeterministicPublishingAdapter(),
    )

    retake = _another_render(
        engine, tmp_path, storyboard_id=_storyboard_of(engine, bundle["asset_id"])
    )
    verdict = evaluate_publishing_gate(engine, retake, ch_id)

    assert verdict["eligible"] is False
    duplicate = next(c for c in verdict["checks"] if c["check_name"] == "DUPLICATE_PROTECTION_GATE")
    assert duplicate["passed"] is False
    # The refusal names the video already on the channel, so the Owner can go and look at it.
    assert published["remote_video_id"] in duplicate["detail"]
    assert "o altă randare a aceluiași scenariu" in duplicate["detail"]
    assert any("același film este deja pe acest canal" in r for r in verdict["reasons"])
    assert verdict["reason_codes"] == ["DUPLICATE_FILM"]


def test_a_second_storyboard_from_one_script_is_still_the_same_film(engine, tmp_path):
    seed_default_channels(engine)
    ch_id = list_channels(engine)[0]["id"]
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    publish_media_asset(
        engine,
        media_asset_id=bundle["asset_id"],
        channel_id=ch_id,
        title="JWST Deep Field Discovery",
        description="Exploring early galaxies.",
        tags=[],
        privacy_status="private",
        correlation_id=str(uuid4()),
        provider=DeterministicPublishingAdapter(),
    )

    # Re-planned, re-shot, re-rendered — and the same script, so the same film.
    replanned = _another_render(
        engine,
        tmp_path,
        storyboard_id=_storyboard_of(engine, bundle["asset_id"]),
        script_id=bundle["script_id"],
    )
    assert evaluate_publishing_gate(engine, replanned, ch_id)["eligible"] is False


def test_the_same_film_may_still_go_to_a_second_channel(engine, tmp_path):
    seed_default_channels(engine)
    channels = list_channels(engine)
    first, second = channels[0]["id"], channels[1]["id"]
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    publish_media_asset(
        engine,
        media_asset_id=bundle["asset_id"],
        channel_id=first,
        title="JWST Deep Field Discovery",
        description="Exploring early galaxies.",
        tags=[],
        privacy_status="private",
        correlation_id=str(uuid4()),
        provider=DeterministicPublishingAdapter(),
    )

    # The gate is per channel on purpose: a studio with two channels may carry one film on
    # both. What it must not do is put the same film on the SAME channel twice.
    retake = _another_render(
        engine, tmp_path, storyboard_id=_storyboard_of(engine, bundle["asset_id"])
    )
    assert evaluate_publishing_gate(engine, retake, second)["eligible"] is True
    with Session(engine) as session:
        assert bundle["script_id"] in published_films(session, first)
        assert published_films(session, second) == {}


def test_a_publication_that_failed_does_not_block_the_film(engine, tmp_path):
    seed_default_channels(engine)
    ch_id = list_channels(engine)[0]["id"]
    bundle = _create_verified_asset_bundle(engine, tmp_path)

    # Nothing reached the channel, so nothing must stand in the way of trying again.
    with Session(engine) as session, session.begin():
        session.add(
            PublicationRecord(
                id=str(uuid4()),
                channel_id=ch_id,
                media_asset_id=bundle["asset_id"],
                title="JWST Deep Field Discovery",
                description="Exploring early galaxies.",
                tags_json=[],
                privacy_status="private",
                status="FAILED_PERMANENT",
                idempotency_key=str(uuid4()),
                error_detail="The upload was refused.",
                created_at=utc_now(),
            )
        )

    retake = _another_render(
        engine, tmp_path, storyboard_id=_storyboard_of(engine, bundle["asset_id"])
    )
    assert evaluate_publishing_gate(engine, retake, ch_id)["eligible"] is True
    with Session(engine) as session:
        assert published_films(session, ch_id) == {}


def test_every_description_carries_the_disclosure_and_the_creator(engine, tmp_path):
    """The Owner's rule: every film's description says it was made with generative AI by the
    AMN-AI pipeline, links the studio's site once there is one, and credits INSIDE THE NEXUS.
    Added on the one road every upload takes, once, whatever the Publisher wrote."""
    from types import SimpleNamespace

    from app.publishing.services import (
        AI_DISCLOSURE,
        channel_link,
        publication_footer,
        with_footer,
    )

    with_site = publication_footer(engine, "https://example.org/amn-ai", None)
    assert with_site == f"{AI_DISCLOSURE} https://example.org/amn-ai"
    assert publication_footer(engine, "", None) == AI_DISCLOSURE  # no site yet: the sentence stands

    handle = SimpleNamespace(
        channel_snapshot={"custom_url": "@insidethenexusai"}, remote_channel_id="UC1"
    )
    assert channel_link(handle) == "https://www.youtube.com/@insidethenexusai"
    as_text = SimpleNamespace(
        channel_snapshot='{"custom_url": "@insidethenexusai"}', remote_channel_id="UC1"
    )
    assert channel_link(as_text) == "https://www.youtube.com/@insidethenexusai"
    bare = SimpleNamespace(channel_snapshot=None, remote_channel_id="UC1")
    assert channel_link(bare) == "https://www.youtube.com/channel/UC1"

    credited = publication_footer(engine, None, "INSIDE THE NEXUS")
    assert credited.endswith("Created by INSIDE THE NEXUS")  # no connection in a fresh studio

    once = with_footer("What the film shows.", with_site)
    assert once == f"What the film shows.\n\n{with_site}"
    assert with_footer(once, with_site) == once  # passed through twice, written once
    long = with_footer("x" * 6000, with_site)
    assert len(long) <= 5000 and long.endswith(with_site)

    seed_default_channels(engine)
    channel_id = list_channels(engine)[0]["id"]
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    published = publish_media_asset(
        engine,
        media_asset_id=bundle["asset_id"],
        channel_id=channel_id,
        title="JWST Deep Field Discovery",
        description="Exploring early galaxies.",
        tags=[],
        privacy_status="private",
        correlation_id=str(uuid4()),
        provider=DeterministicPublishingAdapter(),
        footer=with_site,
    )
    assert published["description"] == f"Exploring early galaxies.\n\n{with_site}"


def test_a_film_of_stripes_fails_quality_control(engine, tmp_path):
    """A still still broken after one more attempt is named in quality control, and fails it."""
    from app.media.qc import evaluate_media_qc

    bundle = _create_verified_asset_bundle(engine, tmp_path)
    with Session(engine) as session, session.begin():
        job = session.scalars(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == bundle["asset_id"])
        ).first()
        job.production_json = {
            "degenerate_stills": [
                {"scene_index": 5, "reason": "vertical stripes, no scene (structure 0.96)"}
            ]
        }
    evaluate_media_qc(engine, bundle["asset_id"], str(uuid4()))
    with Session(engine) as session:
        report = session.scalars(
            select(QualityControlReport)
            .where(QualityControlReport.media_asset_id == bundle["asset_id"])
            .order_by(QualityControlReport.verified_at.desc())
        ).first()
        assert report.status == "FAILED"
        assert report.checks_json["content_integrity_qc"]["passed"] is False
        assert any("Scene 5: vertical stripes" in reason for reason in report.failure_reasons_json)


# --------------------------------------------------------------------------------------------
# Publishing truth (2026-10-02). PUB-04: `execute_publication` uploaded on the strength of the
# gate it ran when the intent was made, so a VALIDATED or retried row went up after the
# Owner's STOP, after a newer failed QC report, or under a policy he had since changed.
# PUB-14: the gate checked that a file existed, not that it was the file QC passed. PUB-12:
# a failure reached nobody, and a row handed to the Owner had no way back from the page.
# --------------------------------------------------------------------------------------------

from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from app.agents.models import AgentMessage  # noqa: E402
from app.models import DomainEvent  # noqa: E402
from app.providers.publishing_base import UploadResult  # noqa: E402
from app.publishing.services import execute_publication  # noqa: E402


class CountingPublisher(DeterministicPublishingAdapter):
    def __init__(self, outcome: str = "CONFIRMED") -> None:
        super().__init__()
        self.outcome = outcome
        self.uploads = 0

    async def upload_video(self, file_path: Path, **kwargs: Any) -> UploadResult:
        self.uploads += 1
        if self.outcome == "CONFIRMED":
            return await super().upload_video(file_path, **kwargs)
        return UploadResult(
            remote_video_id="",
            remote_url="",
            status=self.outcome,
            error_detail="Upload stream interrupted: connection reset",
        )


def _validated(engine, tmp_path, **intent: Any) -> tuple[dict, str, str]:
    seed_default_channels(engine)
    channel_id = list_channels(engine)[0]["id"]
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    fields: dict[str, Any] = {
        "title": "JWST Deep Field Discovery",
        "description": "Exploring early galaxies.",
        "tags": [],
        "privacy_status": "private",
        "idempotency_key": str(uuid4()),
        "correlation_id": str(uuid4()),
    }
    fields.update(intent)
    publication = create_publication_intent(
        engine, channel_id=channel_id, media_asset_id=bundle["asset_id"], **fields
    )
    assert publication["status"] == "VALIDATED"
    return publication, channel_id, bundle["asset_id"]


def _owner_letters(engine) -> list[AgentMessage]:
    with Session(engine) as session:
        return [
            row
            for row in session.scalars(
                select(AgentMessage).where(AgentMessage.intent == "ESCALATE")
            )
            if row.to_agent_id is None and (row.body_json or {}).get("to") == "Owner"
        ]


def _stop(engine) -> None:
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = True


def _newer_failed_qc(engine, asset_id: str) -> None:
    with Session(engine) as session, session.begin():
        session.add(
            QualityControlReport(
                id=str(uuid4()),
                media_asset_id=asset_id,
                status="FAILED",
                score=0.2,
                checks_json={"technical": {"passed": False}},
                failure_reasons_json=["re-measured"],
                verified_at="2999-01-01T00:00:00+00:00",
            )
        )


def _replaced_file(engine, asset_id: str) -> None:
    with Session(engine) as session:
        path = Path(session.get(MediaAsset, asset_id).uri_or_path)
    path.write_bytes(b"another film entirely, written after quality control passed")


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda engine, asset_id: _stop(engine), "AUTONOMY_STOPPED"),
        (_newer_failed_qc, "QC_NOT_PASSED"),
        (_replaced_file, "MEDIA_HASH_MISMATCH"),
    ],
)
def test_execution_runs_the_gate_again_and_uploads_nothing_it_refuses(
    engine, tmp_path, change, code
):
    publication, _, asset_id = _validated(engine, tmp_path)
    change(engine, asset_id)
    publisher = CountingPublisher()

    result = execute_publication(engine, publisher, publication["id"], str(uuid4()))

    assert publisher.uploads == 0
    assert result["status"] == "BLOCKED_GATE"
    events = []
    with Session(engine) as session:
        events = list(
            session.scalars(
                select(DomainEvent).where(
                    DomainEvent.aggregate_id == publication["id"],
                    DomainEvent.event_type == "publishing.gate_failed_at_execution",
                )
            )
        )
    assert len(events) == 1 and code in events[0].payload["gate_reason_codes"]


def test_a_retried_row_is_refused_too_once_the_owner_changed_the_policy(engine, tmp_path):
    from app.publishing.services import change_publish_policy  # noqa: PLC0415
    from test_publish_policy import _command, _to_production  # noqa: PLC0415

    _to_production(engine)
    seed_default_channels(engine)
    channel_id = list_channels(engine)[0]["id"]
    change_publish_policy(engine, channel_id, _command(autonomous_privacy="unlisted"))
    publication, _, _ = _validated(engine, tmp_path, privacy_status="unlisted", policy_version=2)
    with Session(engine) as session, session.begin():
        session.get(PublicationRecord, publication["id"]).status = "FAILED_RETRYABLE"
    change_publish_policy(
        engine, channel_id, _command(expected_version=2, autonomous_privacy="private")
    )
    publisher = CountingPublisher()

    result = execute_publication(engine, publisher, publication["id"], str(uuid4()))

    assert publisher.uploads == 0
    assert result["status"] == "BLOCKED_GATE"
    assert "versiunea" in (result["error_detail"] or "")


def test_the_gate_compares_the_file_with_the_one_quality_control_passed(engine, tmp_path):
    seed_default_channels(engine)
    channel_id = list_channels(engine)[0]["id"]
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    assert evaluate_publishing_gate(engine, bundle["asset_id"], channel_id)["eligible"]

    _replaced_file(engine, bundle["asset_id"])
    verdict = evaluate_publishing_gate(engine, bundle["asset_id"], channel_id)

    assert not verdict["eligible"]
    assert verdict["reason_codes"] == ["MEDIA_HASH_MISMATCH"]
    assert len(verdict["checks"]) == 5
    assert "controlul calității" in verdict["reasons"][0]


@pytest.mark.parametrize(
    ("outcome", "status"), [("FAILED", "FAILED_FINAL"), ("UNKNOWN", "REMOTE_UNKNOWN")]
)
def test_a_failed_or_unknown_upload_writes_the_owner_one_letter_in_romanian(
    engine, tmp_path, outcome, status
):
    publication, _, _ = _validated(engine, tmp_path)

    result = execute_publication(engine, CountingPublisher(outcome), publication["id"], "c1")

    assert result["status"] == status
    letters = _owner_letters(engine)
    assert len(letters) == 1
    letter = letters[0]
    assert "JWST Deep Field Discovery" in letter.subject
    assert letter.body_json["publication_id"] == publication["id"]
    assert letter.body_json["status"] == status
    # The adapter's English stays in the record's technical detail, not in his letter.
    assert "Upload stream interrupted" not in (letter.body_text or "")
    assert "Main Channel A" in (letter.body_text or "")


def _resolve(client, headers, publication_id: str, body: dict) -> Any:
    return client.post(
        f"/api/v1/publishing/publications/{publication_id}/resolve", headers=headers, json=body
    )


def test_the_owner_resolves_a_publication_the_studio_could_not(client, headers, engine, tmp_path):
    publication, _, _ = _validated(engine, tmp_path)
    with Session(engine) as session, session.begin():
        session.get(PublicationRecord, publication["id"]).status = "NEEDS_RECONCILIATION"
    command = {"command_id": str(uuid4()), "found": True, "remote_video_id": "dQw4w9WgXcQ"}

    assert _resolve(client, {}, publication["id"], command).status_code == 401
    first = _resolve(client, headers, publication["id"], command)
    again = _resolve(client, headers, publication["id"], command)

    assert first.status_code == 200, first.text
    assert first.json()["status"] == "PUBLISHED"
    assert first.json()["remote_video_id"] == "dQw4w9WgXcQ"
    assert again.json() == first.json()
    reused = _resolve(
        client, headers, publication["id"], {**command, "remote_video_id": "otherid0001"}
    )
    assert reused.status_code == 409
    with Session(engine) as session:
        events = session.scalars(
            select(DomainEvent).where(
                DomainEvent.aggregate_id == publication["id"],
                DomainEvent.event_type == "publishing.resolved_by_owner",
            )
        ).all()
    assert len(events) == 1


def test_the_owner_says_the_film_is_not_there_and_it_may_be_tried_again(
    client, headers, engine, tmp_path
):
    publication, _, _ = _validated(engine, tmp_path)
    with Session(engine) as session, session.begin():
        session.get(PublicationRecord, publication["id"]).status = "NEEDS_RECONCILIATION"

    answer = _resolve(
        client, headers, publication["id"], {"command_id": str(uuid4()), "found": False}
    )

    assert answer.status_code == 200
    assert answer.json()["status"] == "FAILED_RETRYABLE"
    # Only a row the studio could not settle is his to settle: a published one is not.
    done, _, _ = _validated(engine, tmp_path / "other")
    refused = _resolve(client, headers, done["id"], {"command_id": str(uuid4()), "found": False})
    assert refused.status_code == 409
    # Found, without the video's id, is not an answer.
    missing = _resolve(
        client, headers, publication["id"], {"command_id": str(uuid4()), "found": True}
    )
    assert missing.status_code == 422


def test_every_publication_state_has_its_words_on_both_sides():
    from app.wording import publication_status  # noqa: PLC0415

    assert publication_status("NEEDS_RECONCILIATION") == "de verificat de tine pe canal"
    assert publication_status("BLOCKED_GATE") == "oprit de poarta de publicare"
    page = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "dialog_words.js").read_text(
        encoding="utf-8"
    )
    assert "NEEDS_RECONCILIATION: 'de verificat de tine pe canal'" in page
    assert "BLOCKED_GATE: 'oprit de poarta de publicare'" in page


# ------------------------------------------------ sources and the Shorts length per channel --
# Audit PUB-10 / Q9 / PUB-15 (2026-10-02). Before: a factual film's description listed none of
# the sources its verified claims rest on (the Publisher was handed the narration only), and
# quality control refused any Short over 70 seconds on every channel, while YouTube has taken
# vertical Shorts up to 3 minutes since 2024-10-15.


def _sources_for(engine, asset_id: str, urls: list[tuple[str, str]]) -> None:
    """Give the film's script one claim per (url, status), each resting on its own source."""
    from app.factual.models import SourceSnapshot

    with Session(engine) as session, session.begin():
        job = session.scalars(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == asset_id)
        ).one()
        board = session.get(Storyboard, job.storyboard_id)
        script = session.get(ScriptDraft, board.script_draft_id)
        ids = list(script.claim_ids_json)
        for n, (url, status) in enumerate(urls):
            source_id, claim_id = str(uuid4()), str(uuid4())
            session.add(
                SourceSnapshot(
                    id=source_id,
                    topic_id=script.topic_id,
                    url=url,
                    title=f"Source {n}",
                    publisher="Agency",
                    content_hash="0" * 64,
                    raw_content="text",
                    sanitized_content="text",
                    fetched_at=utc_now(),
                )
            )
            session.add(
                FactualClaim(
                    id=claim_id,
                    source_id=source_id,
                    topic_id=script.topic_id,
                    claim_text=f"Claim {n}.",
                    status=status,
                    created_at=utc_now(),
                )
            )
            ids.append(claim_id)
        script.claim_ids_json = ids


def test_a_factual_description_lists_the_sources_of_its_supported_claims(
    engine, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from app.publishing.services import film_sources

    # The heading follows the upload language; the studio here speaks English.
    monkeypatch.setattr(
        "app.publishing.services.studio_settings",
        lambda: SimpleNamespace(content_language="en"),
    )
    seed_default_channels(engine)
    channel_id = next(c["id"] for c in list_channels(engine) if c["channel_type"] == "MAIN_FACTUAL")
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    _sources_for(
        engine,
        bundle["asset_id"],
        [
            ("https://science.nasa.gov/webb/", "SUPPORTED"),
            ("https://science.nasa.gov/webb/", "SUPPORTED"),  # the same page twice
            ("https://esa.int/webb", "SUPPORTED"),
            ("https://refuted.example.org/x", "REFUTED"),
            ("https://uncertain.example.org/y", "UNCERTAIN"),
            ("https://a.example.org/1", "SUPPORTED"),
            ("https://b.example.org/2", "SUPPORTED"),
            ("https://c.example.org/3", "SUPPORTED"),
            ("https://d.example.org/4", "SUPPORTED"),
            ("javascript:alert(1)", "SUPPORTED"),
        ],
    )
    with Session(engine) as session:
        urls = film_sources(session, bundle["asset_id"])
    assert urls == [
        "https://science.nasa.gov/webb/",
        "https://esa.int/webb",
        "https://a.example.org/1",
        "https://b.example.org/2",
        "https://c.example.org/3",
    ]

    # A script whose claims are not all verified never leaves the studio (the gate's own
    # rule); the film that goes out cites only the SUPPORTED ones.
    with Session(engine) as session, session.begin():
        script = session.get(ScriptDraft, bundle["script_id"])
        kept = session.scalars(
            select(FactualClaim.id).where(
                FactualClaim.id.in_(script.claim_ids_json), FactualClaim.status == "SUPPORTED"
            )
        ).all()
        script.claim_ids_json = [cid for cid in script.claim_ids_json if cid in set(kept)]
    footer = "Disclosure: this video was produced with generative AI."
    published = publish_media_asset(
        engine,
        media_asset_id=bundle["asset_id"],
        channel_id=channel_id,
        title="JWST Deep Field Discovery",
        description="Exploring early galaxies.",
        tags=[],
        privacy_status="private",
        correlation_id=str(uuid4()),
        provider=DeterministicPublishingAdapter(),
        footer=footer,
    )
    description = published["description"]
    assert description.startswith("Exploring early galaxies.")
    assert description.endswith(footer)
    block = description[description.index("Sources:") : description.index(footer)]
    assert [line for line in block.splitlines()[1:] if line.strip()] == urls
    assert "refuted.example.org" not in description and "javascript" not in description
    assert description.count("Sources:") == 1


def test_an_episode_description_lists_no_sources(engine, tmp_path):
    from app.publishing.services import film_sources, with_sources

    bundle = _create_verified_asset_bundle(engine, tmp_path)
    _sources_for(engine, bundle["asset_id"], [("https://esa.int/webb", "SUPPORTED")])
    with Session(engine) as session, session.begin():
        job = session.scalars(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == bundle["asset_id"])
        ).one()
        session.get(Storyboard, job.storyboard_id).series_key = "office_serial"
    with Session(engine) as session:
        assert film_sources(session, bundle["asset_id"]) == []
    # And the block is never written for no source.
    assert with_sources("An episode.", []) == "An episode."


def test_the_sources_block_is_written_once_above_the_footer():
    from app.publishing.services import with_sources

    footer = "Disclosure: this video was produced with generative AI."
    body = f"About the film.\n\n{footer}"
    once = with_sources(body, ["https://esa.int/webb"])
    assert once == f"About the film.\n\nSources:\nhttps://esa.int/webb\n\n{footer}"
    assert with_sources(once, ["https://esa.int/webb"]) == once


def _qc_duration(engine, tmp_path, monkeypatch, seconds: float, *, serial: bool = False):
    from app.media.qc import evaluate_media_qc

    seed_default_channels(engine)
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    if serial:
        with Session(engine) as session, session.begin():
            job = session.scalars(
                select(VideoRenderJob).where(VideoRenderJob.output_asset_id == bundle["asset_id"])
            ).one()
            session.get(Storyboard, job.storyboard_id).series_key = "office_serial"
    monkeypatch.setattr(
        "app.media.qc.probe_media_file",
        lambda path: {
            "available": True,
            "ok": True,
            "width": 1080,
            "height": 1920,
            "duration_seconds": seconds,
            "video_codec": "h264",
            "has_audio": True,
        },
    )
    evaluate_media_qc(engine, bundle["asset_id"], str(uuid4()))
    with Session(engine) as session:
        report = session.scalars(
            select(QualityControlReport)
            .where(QualityControlReport.media_asset_id == bundle["asset_id"])
            .order_by(QualityControlReport.verified_at.desc())
        ).first()
        return report.checks_json["technical_qc"], list(report.failure_reasons_json)


@pytest.mark.parametrize(
    ("seconds", "serial", "passes"),
    [
        (180.0, False, True),  # YouTube's Shorts limit, exactly (the Owner, 2026-10-16)
        # YouTube's wall is absolute: the slack never takes a film past it (2026-10-16).
        (180.9, False, False),
        (181.5, False, False),
        (179.9, True, True),  # the serial's 90-180 s window
        (181.5, True, False),
        (9.5, False, False),  # the floor is unchanged
    ],
)
def test_the_shorts_length_is_read_per_channel(
    engine, tmp_path, monkeypatch, seconds, serial, passes
):
    technical, reasons = _qc_duration(engine, tmp_path, monkeypatch, seconds, serial=serial)
    assert technical["max_duration_seconds"] == 180
    assert technical["duration_valid"] is passes
    assert any("durata" in reason.lower() for reason in reasons) is not passes


def test_a_channel_may_take_shorts_up_to_three_minutes(engine, tmp_path, monkeypatch):
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        channel = session.scalars(
            select(ChannelRecord).where(ChannelRecord.channel_type == "MAIN_FACTUAL")
        ).one()
        channel.shorts_max_seconds = 180
    technical, _ = _qc_duration(engine, tmp_path / "a", monkeypatch, 179.0)
    assert technical["max_duration_seconds"] == 180 and technical["duration_valid"] is True
    technical, _ = _qc_duration(engine, tmp_path / "b", monkeypatch, 181.5)
    assert technical["duration_valid"] is False


def test_the_slack_is_forgiven_only_under_youtubes_wall(engine, tmp_path, monkeypatch):
    """The wall is exact (2026-10-16, «pauza vocii»: every pause is planned and fitted under
    min(the channel's maximum, 180 s)): a channel the Owner set to 150 s takes 150 s and not a
    second more, and one at 180 never takes a film past 180 (review finding 19)."""
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        channel = session.scalars(
            select(ChannelRecord).where(ChannelRecord.channel_type == "MAIN_FACTUAL")
        ).one()
        channel.shorts_max_seconds = 150
    technical, _ = _qc_duration(engine, tmp_path / "a", monkeypatch, 150.0)
    assert technical["max_duration_seconds"] == 150 and technical["duration_valid"] is True
    technical, _ = _qc_duration(engine, tmp_path / "a2", monkeypatch, 150.9)
    assert technical["duration_valid"] is False
    with Session(engine) as session, session.begin():
        session.scalars(
            select(ChannelRecord).where(ChannelRecord.channel_type == "MAIN_FACTUAL")
        ).one().shorts_max_seconds = 180
    technical, reasons = _qc_duration(engine, tmp_path / "b", monkeypatch, 180.5)
    assert technical["duration_valid"] is False
    assert any("limitele unui Short" in reason for reason in reasons), reasons
