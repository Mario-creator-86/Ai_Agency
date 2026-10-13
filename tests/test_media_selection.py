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
from app.integrations.models import (
    Integration,
    MediaProductionConfig,
    ProviderResource,
    ServiceSelection,
)
from app.integrations.vault import CredentialVault
from app.media.factory import describe, image_provider, tts_provider
from app.media.toolchain import find_ffmpeg
from app.providers.elevenlabs import ElevenLabsTTSAdapter
from app.providers.media_http import MediaProviderError
from app.providers.openai_media import OpenAIImageAdapter
from app.services import append_event, utc_now
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
        if kind == "elevenlabs" and config.get("model") and config.get("voice_id"):
            session.flush()
            session.add(
                MediaProductionConfig(
                    integration_id=identifier,
                    model_id=config["model"],
                    voice_id=config["voice_id"],
                    version=1,
                    updated_at=utc_now(),
                )
            )
            for resource_type, remote_id in (
                ("MODEL", config["model"]),
                ("VOICE", config["voice_id"]),
            ):
                session.add(
                    ProviderResource(
                        id=str(uuid4()),
                        integration_id=identifier,
                        resource_type=resource_type,
                        remote_id=remote_id,
                        name=remote_id,
                        api_available=True,
                        last_seen_at=utc_now(),
                        api_metadata={"can_do_text_to_speech": True}
                        if resource_type == "MODEL"
                        else {},
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
        engine,
        vault,
        "elevenlabs",
        "VERIFIED",
        {"voice_id": "v1", "model": "test-model"},
        {"api_key": "k"},
    )
    select(engine, "voice", identifier)
    assert tts_provider(engine, vault) is not None

    select(engine, "voice", None)
    assert tts_provider(engine, vault) is None


def test_a_vendor_with_no_adapter_yet_yields_no_provider(engine, vault):
    """Replicate is in the catalogue but has no adapter: 'no generator', not a substitute."""
    identifier = add_integration(
        engine, vault, "replicate", "ACCESS_VERIFIED", {"model": "owner/model"}, {"api_key": "k"}
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
        {"voice_id": "v-narrator", "model": "test-model"},
        {"api_key": "k"},
    )
    select(engine, "voice", identifier)

    provider = tts_provider(engine, vault)

    assert isinstance(provider, ElevenLabsTTSAdapter)
    assert provider.voice_id == "v-narrator"
    assert describe(engine, vault)["voice_provider"] == "ELEVENLABS"


def test_image_and_voice_are_selected_independently(engine, vault):
    voice = add_integration(
        engine,
        vault,
        "elevenlabs",
        "VERIFIED",
        {"voice_id": "v1", "model": "test-model"},
        {"api_key": "k"},
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
        # Real stills and no motion model: pushed stills, which only a TEST film may be
        # without the Owner's LOCAL_MOVE (PRODUCTION refuses it before the encode).
        environment="TEST",
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


# ---------------------------------------------------------------------------
# A second vendor when the first refuses
# ---------------------------------------------------------------------------
# The Owner approves an alternative; the studio tries it once and records what the attempt
# cost. With nothing approved the chain is one vendor long and a refusal ends the same way
# it always did — the placeholder still, which QC blocks from publication.


class RefusingImages:
    """An image vendor that refuses, or answers, and counts how often it was asked."""

    def __init__(self, name, integration_id, model, *, refusals=0):
        self.PROVIDER_NAME = name
        self.integration_id = integration_id
        self.model = model
        self.refusals = refusals
        self.asked = 0

    async def health_check(self):
        return {"status": "HEALTHY", "detail": ""}

    async def generate_image(
        self, prompt, *, width=1080, height=1920, style=None, seed=None, extra=None
    ):
        from app.providers.media_base import ImageResult

        self.asked += 1
        if self.asked <= self.refusals:
            raise MediaProviderError(f"{self.PROVIDER_NAME} refused this prompt")
        return ImageResult(image_bytes=b"\x89PNG", format="png", width=8, height=8, prompt=prompt)


def priced_model(engine, integration_id, model_id, per_image_usd):
    with Session(engine) as session, session.begin():
        session.add(
            ProviderResource(
                id=str(uuid4()),
                integration_id=integration_id,
                resource_type="MODEL",
                remote_id=model_id,
                name=model_id,
                api_available=True,
                last_seen_at=utc_now(),
                api_metadata={},
                pricing={"per_image_usd": per_image_usd},
            )
        )


def test_the_chain_is_the_resolved_vendor_then_the_owners_approved_one(engine, vault):
    from app.media.factory import image_adapter_chain

    first = add_integration(
        engine, vault, "openai_media", "VERIFIED", {"model": "a"}, {"api_key": "k"}
    )
    second = add_integration(
        engine, vault, "openai_media", "VERIFIED", {"model": "b"}, {"api_key": "k"}
    )
    resolved = {
        "valid": True,
        "integration_id": first,
        "model_id": "a",
        "fallbacks": [{"valid": True, "integration_id": second, "model_id": "b"}],
    }

    chain = image_adapter_chain(engine, vault, resolved, environment="PRODUCTION")

    assert [adapter.integration_id for adapter in chain] == [first, second]
    assert [adapter.model for adapter in chain] == ["a", "b"]


def test_with_no_approved_fallback_the_chain_is_one_vendor(engine, vault):
    from app.media.factory import image_adapter_chain

    first = add_integration(
        engine, vault, "openai_media", "VERIFIED", {"model": "a"}, {"api_key": "k"}
    )
    resolved = {"valid": True, "integration_id": first, "model_id": "a", "fallbacks": []}

    assert len(image_adapter_chain(engine, vault, resolved, environment="PRODUCTION")) == 1


def test_a_test_render_still_buys_the_cheapest_compatible_model(engine, vault):
    """TEST takes the cheapest model that can do the job — a fallback does not change that."""
    from app.media.factory import image_adapter_chain

    first = add_integration(
        engine, vault, "openai_media", "VERIFIED", {"model": "dear"}, {"api_key": "k"}
    )
    second = add_integration(
        engine, vault, "openai_media", "VERIFIED", {"model": "cheap"}, {"api_key": "k"}
    )
    priced_model(engine, first, "dear", 0.19)
    priced_model(engine, second, "cheap", 0.02)
    resolved = {
        "valid": True,
        "integration_id": first,
        "model_id": "dear",
        "fallbacks": [{"valid": True, "integration_id": second, "model_id": "cheap"}],
    }

    in_test = image_adapter_chain(engine, vault, resolved, environment="TEST")
    in_production = image_adapter_chain(engine, vault, resolved, environment="PRODUCTION")

    assert [a.model for a in in_test] == ["cheap", "dear"]
    # Production keeps the Owner's order: the resolved vendor first, the alternative after.
    assert [a.model for a in in_production] == ["dear", "cheap"]


def test_the_second_vendor_is_tried_once_when_the_first_refuses_and_both_attempts_are_costed(
    engine, vault
):
    import asyncio

    from app.media.factory import still_from_chain

    first = add_integration(
        engine, vault, "openai_media", "VERIFIED", {"model": "a"}, {"api_key": "k"}
    )
    second = add_integration(
        engine, vault, "openai_media", "VERIFIED", {"model": "b"}, {"api_key": "k"}
    )
    priced_model(engine, first, "a", 0.04)
    priced_model(engine, second, "b", 0.07)
    refuses = RefusingImages("FIRST", first, "a", refusals=1)
    answers = RefusingImages("SECOND", second, "b")

    result, attempts = asyncio.run(
        still_from_chain(engine, [refuses, answers], "a telescope over a dark field")
    )

    assert result.width == 8
    assert (refuses.asked, answers.asked) == (1, 1), "the chain is bounded: one alternative"
    assert [a["provider"] for a in attempts] == ["FIRST", "SECOND"]
    assert [a["succeeded"] for a in attempts] == [False, True]
    # Each attempt says what it was worth at the price the studio has recorded.
    assert [a["estimated_usd"] for a in attempts] == [0.04, 0.07]
    assert attempts[0]["error"]


def test_when_every_approved_vendor_refuses_the_render_falls_back_to_the_still_as_today(
    engine, vault
):
    import asyncio

    from app.media.factory import still_from_chain

    first = add_integration(
        engine, vault, "openai_media", "VERIFIED", {"model": "a"}, {"api_key": "k"}
    )
    refuses = RefusingImages("ONLY", first, "a", refusals=5)

    with pytest.raises(MediaProviderError) as refusal:
        asyncio.run(still_from_chain(engine, [refuses], "a telescope"))

    assert refuses.asked == 1
    # The attempts travel with the error so the books can price what was tried.
    assert [a["provider"] for a in refusal.value.attempts] == ["ONLY"]


def test_an_attempt_on_a_model_with_no_recorded_price_is_none_and_never_zero(engine, vault):
    import asyncio

    from app.media.factory import still_from_chain

    first = add_integration(
        engine, vault, "openai_media", "VERIFIED", {"model": "a"}, {"api_key": "k"}
    )
    answers = RefusingImages("ONLY", first, "a")

    _result, attempts = asyncio.run(still_from_chain(engine, [answers], "a telescope"))

    assert attempts[0]["estimated_usd"] is None
