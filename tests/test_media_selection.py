"""Which media provider a render uses, and what the resulting asset is allowed to claim.

The rule under all of it: a rendered asset records the generator that actually produced its
frames. With no verified provider the studio still assembles a video — useful to look at — but
it is labelled as placeholder content and QC blocks it from publication. The failure this
prevents is a render made from placeholder frames being carried into the publishing gate as
though a provider had made it.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.integrations.models import Integration, ServiceSelection
from app.integrations.vault import CredentialVault
from app.media.factory import describe, image_provider, tts_provider
from app.media.toolchain import find_ffmpeg
from app.providers.elevenlabs import ElevenLabsTTSAdapter
from app.providers.openai_media import OpenAIImageAdapter
from app.services import append_event
from sqlalchemy.orm import Session


@pytest.fixture
def vault(tmp_path):
    return CredentialVault(tmp_path / "test.credentials.key")


def add_integration(engine, vault, kind: str, status: str, config: dict, secrets: dict) -> str:
    identifier = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "settings.integration_saved", "integration", identifier, 1, {}, str(uuid4())
        )
        session.add(
            Integration(
                id=identifier,
                kind=kind,
                name=kind,
                config=config,
                encrypted_secrets=vault.encrypt(secrets),
                secret_fields=sorted(secrets),
                version=1,
                status=status,
                checked_at=None,
                event_id=event.event_id,
            )
        )
    return identifier


def select(engine, purpose: str, integration_id: str | None) -> None:
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "settings.service_selected", "service_selection", purpose, 1, {}, str(uuid4())
        )
        session.merge(
            ServiceSelection(
                purpose=purpose, integration_id=integration_id, version=1, event_id=event.event_id
            )
        )


# ---------------------------------------------------------------------------
# When there is no usable provider
# ---------------------------------------------------------------------------


def test_nothing_configured_means_no_provider(engine, vault):
    assert image_provider(engine, vault) is None
    assert tts_provider(engine, vault) is None
    assert describe(engine, vault) == {"image_provider": None, "voice_provider": None}


def test_a_saved_but_unverified_connection_is_not_used(engine, vault):
    """SAVED means the key was typed in, not that the vendor accepted it."""
    identifier = add_integration(
        engine, vault, "openai_media", "SAVED", {"model": "gpt-image-1"}, {"api_key": "k"}
    )
    select(engine, "image", identifier)

    assert image_provider(engine, vault) is None, (
        "an unverified provider would fail mid-render, after the Owner was told it had started"
    )


def test_a_verified_connection_that_was_never_selected_is_not_used(engine, vault):
    add_integration(
        engine, vault, "openai_media", "ACCESS_VERIFIED", {"model": "gpt-image-1"}, {"api_key": "k"}
    )

    assert image_provider(engine, vault) is None


def test_deselecting_a_provider_takes_effect(engine, vault):
    identifier = add_integration(
        engine, vault, "elevenlabs", "ACCESS_VERIFIED", {"voice_id": "v1"}, {"api_key": "k"}
    )
    select(engine, "voice", identifier)
    assert tts_provider(engine, vault) is not None

    select(engine, "voice", None)
    assert tts_provider(engine, vault) is None


def test_a_vendor_with_no_adapter_yet_yields_no_provider(engine, vault):
    """Runway is in the catalogue but has no adapter. That is 'no generator', not a substitute."""
    identifier = add_integration(
        engine, vault, "runway", "ACCESS_VERIFIED", {"model": "gen3"}, {"api_key": "k"}
    )
    select(engine, "video", identifier)

    assert image_provider(engine, vault) is None
    assert tts_provider(engine, vault) is None


def test_a_verified_connection_missing_its_key_yields_no_provider(engine, vault):
    identifier = add_integration(
        engine, vault, "elevenlabs", "ACCESS_VERIFIED", {"voice_id": "v1"}, {}
    )
    select(engine, "voice", identifier)

    assert tts_provider(engine, vault) is None


# ---------------------------------------------------------------------------
# When there is one
# ---------------------------------------------------------------------------


def test_a_verified_and_selected_image_provider_is_used(engine, vault):
    identifier = add_integration(
        engine, vault, "openai_media", "ACCESS_VERIFIED", {"model": "gpt-image-1"}, {"api_key": "k"}
    )
    select(engine, "image", identifier)

    provider = image_provider(engine, vault)

    assert isinstance(provider, OpenAIImageAdapter)
    assert provider.model == "gpt-image-1"
    assert describe(engine, vault)["image_provider"] == "OPENAI_IMAGES"


def test_a_verified_and_selected_voice_provider_carries_its_voice(engine, vault):
    identifier = add_integration(
        engine,
        vault,
        "elevenlabs",
        "ACCESS_VERIFIED",
        {"voice_id": "v-narrator", "model": "eleven_multilingual_v2"},
        {"api_key": "k"},
    )
    select(engine, "voice", identifier)

    provider = tts_provider(engine, vault)

    assert isinstance(provider, ElevenLabsTTSAdapter)
    assert provider.voice_id == "v-narrator"
    assert describe(engine, vault)["voice_provider"] == "ELEVENLABS"


def test_image_and_voice_are_selected_independently(engine, vault):
    voice = add_integration(
        engine, vault, "elevenlabs", "ACCESS_VERIFIED", {"voice_id": "v1"}, {"api_key": "k"}
    )
    select(engine, "voice", voice)

    described = describe(engine, vault)

    assert described["voice_provider"] == "ELEVENLABS"
    assert described["image_provider"] is None, (
        "a voice provider must not stand in for an image provider"
    )


# ---------------------------------------------------------------------------
# What the interface is told
# ---------------------------------------------------------------------------


def test_the_api_reports_placeholder_renders_when_no_image_provider_is_set(client, headers):
    response = client.get("/api/v1/media/providers", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["image_provider"] is None
    assert body["renders_are_publishable"] is False
    assert "substitut" in body["note"]


# ---------------------------------------------------------------------------
# What the rendered asset is allowed to claim
# ---------------------------------------------------------------------------


class StubImageAdapter:
    """A provider that returns a real PNG, standing in for a vendor the Owner has configured."""

    PROVIDER_NAME = "TEST_IMAGE_PROVIDER"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def health_check(self):
        return {"status": "HEALTHY"}

    async def generate_image(self, prompt, *, width=1080, height=1920, **kwargs):
        from app.providers.media_base import ImageResult
        from test_media_providers import png_bytes

        self.prompts.append(prompt)
        return ImageResult(
            image_bytes=png_bytes(1024, 1536),
            format="png",
            width=1024,
            height=1536,
            prompt=prompt,
        )


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")
def test_a_render_without_a_provider_is_labelled_placeholder_and_blocked_by_qc(engine, tmp_path):
    from app.media.assembler import PLACEHOLDER_VISUAL_PROVIDER, assemble_video_job
    from app.media.qc import evaluate_media_qc
    from test_phase5_media import _seeded_storyboard

    storyboard_id, _ = _seeded_storyboard(engine, tmp_path)

    render = assemble_video_job(
        engine, storyboard_id, str(uuid4()), storage_root=tmp_path / "media"
    )

    assert render["visual_source"] == PLACEHOLDER_VISUAL_PROVIDER
    qc = evaluate_media_qc(engine, render["output_asset_id"], str(uuid4()))
    assert qc["status"] == "FAILED"
    assert qc["checks_json"]["content_source_qc"]["passed"] is False


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")
def test_a_render_from_a_real_provider_records_that_provider_and_passes_content_qc(
    engine, tmp_path
):
    """The placeholder block lifts only because a real generator made the frames — and the
    asset says which one, so the claim can be checked afterwards rather than trusted."""
    from app.media.assembler import assemble_video_job
    from app.media.models import MediaAsset
    from app.media.qc import evaluate_media_qc
    from test_phase5_media import _seeded_storyboard

    storyboard_id, _ = _seeded_storyboard(engine, tmp_path)
    adapter = StubImageAdapter()

    render = assemble_video_job(
        engine,
        storyboard_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=adapter,
    )

    assert adapter.prompts, "the provider must actually have been asked for the frames"
    assert render["visual_source"] == "TEST_IMAGE_PROVIDER"
    with Session(engine) as session:
        asset = session.get(MediaAsset, render["output_asset_id"])
    assert asset.provider_name == "TEST_IMAGE_PROVIDER"

    qc = evaluate_media_qc(engine, render["output_asset_id"], str(uuid4()))
    assert qc["checks_json"]["content_source_qc"]["passed"] is True
    assert qc["checks_json"]["content_source_qc"]["provider_name"] == "TEST_IMAGE_PROVIDER"


# ---------------------------------------------------------------------------
# The handover from research to production
# ---------------------------------------------------------------------------


def test_only_approved_scripts_are_offered_to_production(engine):
    """Approval is what the factual gate means. Offering an unapproved draft here would invite
    starting production on claims nobody verified."""
    from app.factual.models import ScriptDraft, TopicIdea
    from app.media.services import list_scripts_awaiting_storyboard
    from app.services import utc_now

    now = utc_now()
    topic_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=topic_id,
                title="Queue fixture",
                topic="space",
                angle="fixture",
                target_audience="test",
                novelty_score=0.9,
                status="SELECTED",
                created_at=now,
            )
        )
        session.flush()
        for index, status in enumerate(
            ["APPROVED", "DRAFT", "VERIFIED_PASS", "BLOCKED_UNVERIFIED_CLAIMS"]
        ):
            session.add(
                ScriptDraft(
                    id=str(uuid4()),
                    topic_id=topic_id,
                    version=index + 1,
                    title=f"Script {status}",
                    target_duration_seconds=45,
                    voiceover_full_text="Narration long enough to store.",
                    scenes_json=[{"scene_index": 1}],
                    status=status,
                    claim_ids_json=[],
                    unverified_claim_ids_json=[],
                    created_at=now,
                )
            )

    waiting = list_scripts_awaiting_storyboard(engine)

    assert [s["title"] for s in waiting] == ["Script APPROVED"]


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")
def test_a_script_leaves_the_queue_once_its_storyboard_exists(engine, tmp_path):
    from app.media.models import Storyboard
    from app.media.services import list_scripts_awaiting_storyboard
    from test_phase5_media import _seeded_storyboard

    storyboard_id, _ = _seeded_storyboard(engine, tmp_path)
    with Session(engine) as session:
        script_id = session.get(Storyboard, storyboard_id).script_draft_id

    waiting = list_scripts_awaiting_storyboard(engine)

    assert script_id not in [s["id"] for s in waiting], (
        "a script already in production must not be offered again"
    )


def test_the_api_exposes_the_queue(client, headers):
    response = client.get("/api/v1/media/scripts/awaiting-storyboard", headers=headers)

    assert response.status_code == 200
    assert response.json()["scripts"] == []
