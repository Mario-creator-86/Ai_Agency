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
- The seed never records a provider as healthy or a model as verified without a response.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from app.agents.models import ModelRecord, ProviderRecord
from app.agents.services import seed_initial_workforce, sync_provider_models
from app.main import register_seeded_ollama
from app.media.models import MediaAsset, QualityControlReport
from app.media.qc import evaluate_media_qc
from app.models import DomainEvent, OwnerPolicy
from app.providers.base import ModelInfo
from app.providers.deterministic_pub import DeterministicPublishingAdapter
from app.providers.ollama import OllamaProvider
from app.providers.registry import ProviderRegistry
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


def _give_provenance(engine, asset_id: str) -> None:
    """Attach the script -> storyboard -> render job chain that the factual gate walks.

    A publishable asset has to be traceable back to a script; the gate now fails anything it
    cannot trace, rather than passing it while claiming "verified factual provenance". The script
    here asserts no factual claims, which is the honest shape for a test whose subject is how an
    upload result gets recorded.
    """
    from app.factual.models import ScriptDraft, TopicIdea
    from app.media.models import Storyboard, VideoRenderJob

    now = utc_now()
    script_id, storyboard_id, topic_id = str(uuid4()), str(uuid4()), str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=topic_id,
                title="Subiect de test",
                topic="Test",
                angle="Test",
                target_audience="test",
                novelty_score=0.5,
                status="SELECTED",
                created_at=now,
            )
        )
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                version=1,
                title="Fara afirmatii factuale",
                target_duration_seconds=10,
                voiceover_full_text="",
                scenes_json=[],
                status="APPROVED",
                claim_ids_json=[],
                unverified_claim_ids_json=[],
                created_at=now,
            )
        )
    # Committed in the same order the pipeline writes them: the storyboard's script must exist
    # before the storyboard references it.
    with Session(engine) as session, session.begin():
        session.add(
            Storyboard(
                id=storyboard_id,
                script_draft_id=script_id,
                title="Storyboard",
                visual_style="MOTION_GRAPHIC",
                aspect_ratio="9:16",
                target_duration_seconds=10,
                status="APPROVED",
                total_scenes=0,
                created_at=now,
            )
        )
        session.add(
            VideoRenderJob(
                id=str(uuid4()),
                storyboard_id=storyboard_id,
                output_asset_id=asset_id,
                status="COMPLETED",
                render_engine="test",
                command_args_json={},
                started_at=now,
                finished_at=now,
            )
        )


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
    assert derive_channel_status("UCrealid", "oauth-ref") == "CONFIGURED"


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
    _give_provenance(engine, asset_id)

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
    assert "Încărcare simulată" in (result["error_detail"] or "")

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
        assert "Autonomia studioului este oprită" in (records[0].error_detail or "")
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


# ---------------------------------------------------------------------------
# Seeded provider and model records
#
# The seed writes intent, never observation. It used to record the Ollama endpoint as
# HEALTHY with a health-check timestamp and its three configured models as available and
# verified, without contacting Ollama at all — so a studio on a machine with no Ollama
# installed showed a healthy provider and three verified models.
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded(engine):
    """The workforce seed, as scripts/bootstrap.py runs it."""
    seed_initial_workforce(engine)
    return engine


def test_seeded_provider_is_not_reported_as_healthy(seeded):
    with Session(seeded) as session:
        providers = list(session.scalars(select(ProviderRecord)))

    assert providers, "the seed must register the Ollama endpoint"
    for provider in providers:
        assert provider.status != "HEALTHY", (
            f"provider {provider.name} is recorded HEALTHY but nothing contacted it"
        )
        assert provider.last_health_check is None, (
            f"provider {provider.name} carries a health-check timestamp for a check that never ran"
        )


def test_seeded_models_are_not_reported_as_available_or_verified(seeded):
    with Session(seeded) as session:
        models = list(session.scalars(select(ModelRecord)))

    assert models, "the seed must record the models the studio expects"
    for model in models:
        assert model.is_available is False, (
            f"model {model.model_name} is marked available without any provider response"
        )
        assert model.last_verified is None, (
            f"model {model.model_name} carries a verification timestamp for a check that never ran"
        )
        assert model.discovery_method == "SEEDED_UNVERIFIED", (
            f"model {model.model_name} claims the provider declared it, but the seed did"
        )


def test_a_model_becomes_available_only_after_the_provider_answers(seeded):
    """The sync is the only path from seeded intent to a measured, available model."""

    class OneModelProvider:
        ADAPTER_VERSION = "test"

        async def list_models(self):
            return [ModelInfo("glm-5.2:cloud", 131072, True)]

    with Session(seeded) as session:
        provider_id = session.scalars(select(ProviderRecord.id)).first()

    registry = ProviderRegistry()
    registry.register(provider_id, OneModelProvider())
    sync_provider_models(seeded, registry, provider_id)

    with Session(seeded) as session:
        provider = session.get(ProviderRecord, provider_id)
        by_name = {m.model_name: m for m in session.scalars(select(ModelRecord))}

    # The model the provider actually named is now available and measured.
    answered = by_name["glm-5.2:cloud"]
    assert answered.is_available is True
    assert answered.last_verified is not None
    assert answered.discovery_method == "DECLARED_BY_PROVIDER"
    assert provider is not None and provider.status == "HEALTHY"

    # The models it did not name stay unavailable.
    for name in ("kimi-k2.6:cloud", "qwen3-coder:480b-cloud"):
        assert by_name[name].is_available is False, f"{name} was never named by the provider"


def test_an_unreachable_provider_is_never_recorded_as_healthy(seeded):
    """A failed sync leaves the record as it was; it must not upgrade anything."""

    class UnreachableProvider:
        ADAPTER_VERSION = "test"

        async def list_models(self):
            raise OSError("connection refused")

    with Session(seeded) as session:
        provider_id = session.scalars(select(ProviderRecord.id)).first()

    registry = ProviderRegistry()
    registry.register(provider_id, UnreachableProvider())
    with pytest.raises(OSError):
        sync_provider_models(seeded, registry, provider_id)

    with Session(seeded) as session:
        provider = session.get(ProviderRecord, provider_id)
        models = list(session.scalars(select(ModelRecord)))

    assert provider is not None and provider.status != "HEALTHY"
    assert provider.last_health_check is None
    assert all(m.is_available is False for m in models)


def test_the_seeded_provider_can_actually_be_checked_by_the_owner(seeded):
    """An unverified record is only honest if the Owner has a way to verify it.

    The seeded provider previously had no adapter registered, so the check and the model
    sync both failed with "no adapter registered" and the seeded claim could never be
    replaced by a measured one.
    """
    registry = ProviderRegistry()
    register_seeded_ollama(seeded, registry)

    with Session(seeded) as session:
        provider_id = session.scalars(select(ProviderRecord.id)).first()

    assert registry.get(provider_id) is not None, (
        "the seeded Ollama endpoint has no adapter, so the Owner cannot verify it"
    )


def test_an_unreachable_provider_reports_that_it_did_not_answer(seeded, client, headers):
    """A dead endpoint must produce an honest 503, not a generic 500 the Owner can't act on."""
    response = client.get("/api/v1/providers/", headers=headers)
    provider_id = response.json()["providers"][0]["id"]
    # A developer machine may genuinely run Ollama on the default port; point the adapter at
    # a port nothing listens on so "unreachable" is deterministic, not environment luck.
    client.app.app.state.registry.register(
        provider_id, OllamaProvider(base_url="http://127.0.0.1:9")
    )

    result = client.post(f"/api/v1/providers/{provider_id}/sync-models", headers=headers)

    assert result.status_code == 503, result.text
    assert "nu a răspuns" in result.json()["detail"]
    assert "nu s-a înregistrat niciun model" in result.json()["detail"]

    after = client.get("/api/v1/providers/", headers=headers).json()["providers"][0]
    assert after["status"] == "NOT_CONFIGURED"
    assert after["last_health_check"] is None


def test_an_asset_with_no_provenance_is_refused_rather_than_declared_verified(engine, tmp_path):
    """The factual gate used to pass anything it could not trace, saying "verified provenance".

    Walking asset -> render job -> storyboard -> script is how the gate learns which claims a
    video makes. When the walk fails it has learned nothing, and an unanswered gate must block
    rather than sign off. 50_CONTENT_GATE_MATRIX.md keeps NOT_APPLICABLE separate from PASS.
    """
    from app.publishing.services import evaluate_publishing_gate

    _clear_stop(engine)
    seed_default_channels(engine)
    channel_id = list_channels(engine)[0]["id"]
    video = tmp_path / "orphan.mp4"
    video.write_bytes(b"\x00" * 2048)
    asset_id = _register_asset(engine, video)

    verdict = evaluate_publishing_gate(engine, asset_id, channel_id)
    gate = next(c for c in verdict["checks"] if c["check_name"] == "FACTUAL_INTEGRITY_GATE")

    assert verdict["eligible"] is False
    assert gate["passed"] is False
    assert "nicio randare nu a produs acest material" in gate["detail"]
    assert gate["data"]["missing"] == "NO_RENDER_JOB"
    # The old wording is the thing being forbidden: it asserted a verification never performed.
    assert "verified factual provenance" not in gate["detail"]


def test_a_claim_referenced_but_absent_is_not_treated_as_supported(engine, tmp_path):
    """A dangling claim id used to disappear from the check entirely.

    The gate loaded the rows that existed and compared only those, so a script citing three
    claims of which two were missing passed as "All 1 referenced claims are SUPPORTED".
    """
    from app.factual.models import ScriptDraft
    from app.publishing.services import evaluate_publishing_gate

    _clear_stop(engine)
    seed_default_channels(engine)
    channel_id = list_channels(engine)[0]["id"]
    video = tmp_path / "dangling.mp4"
    video.write_bytes(b"\x00" * 2048)
    asset_id = _register_asset(engine, video)
    _give_provenance(engine, asset_id)

    invented = str(uuid4())
    with Session(engine) as session, session.begin():
        script = session.scalars(select(ScriptDraft)).first()
        script.claim_ids_json = [invented]

    verdict = evaluate_publishing_gate(engine, asset_id, channel_id)
    gate = next(c for c in verdict["checks"] if c["check_name"] == "FACTUAL_INTEGRITY_GATE")

    assert verdict["eligible"] is False
    assert gate["passed"] is False
    assert gate["data"]["missing_claim_ids"] == [invented]
    assert "1 afirmație citată care nu există în evidență" in gate["detail"]
