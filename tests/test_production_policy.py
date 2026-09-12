"""Two channels, two production policies — the acceptance scenarios from the Owner's brief.

Nexus Curiosity (MAIN_FACTUAL) is FLEXIBLE: every video may choose its own technology from the
discovered resources. Inside The Nexus (OFFICE_SERIAL) is CONSISTENCY_LOCKED: a recurring
character's voice identity survives new defaults, new models and per-episode wishes, and
changes only through an approved identity change. Both share one connection, one discovery
and one Organization default; nothing here names a real model, voice or channel id.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from app.factual.models import FactualClaim, ScriptDraft, TopicIdea
from app.integrations.models import Integration, MediaProductionConfig, ProviderResource
from app.integrations.vault import CredentialVault
from app.media.factory import render_plan
from app.media.models import CharacterBible, StoryboardScene
from app.media.services import generate_storyboard_from_script
from app.models import OwnerPolicy
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

# --------------------------------------------------------------------------- helpers


def connect_elevenlabs(client, headers):
    identifier = str(uuid4())
    response = client.put(
        f"/api/v1/settings/integrations/{identifier}",
        headers=headers,
        json={
            "kind": "elevenlabs",
            "name": "Studio voice account",
            "secrets": {"api_key": f"k-{uuid4()}"},
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "VERIFIED"
    return identifier


def catalog(client, headers, identifier):
    return client.get("/api/v1/settings", headers=headers).json()["provider_catalogs"][identifier]


def set_default(client, headers, identifier, model_id, voice_id, *, allow=True):
    version = catalog(client, headers, identifier)["production"]["version"]
    response = client.put(
        f"/api/v1/settings/integrations/{identifier}/production",
        headers=headers,
        json={
            "model_id": model_id,
            "voice_id": voice_id,
            "allow_production_override": allow,
            "expected_version": version,
        },
    )
    assert response.status_code == 200, response.text


def select_voice(client, headers, identifier):
    version = (
        client.get("/api/v1/settings", headers=headers)
        .json()["selections"]
        .get("voice", {})
        .get("version", 0)
    )
    response = client.put(
        "/api/v1/settings/selections/voice",
        headers=headers,
        json={"integration_id": identifier, "expected_version": version},
    )
    assert response.status_code == 200, response.text


def channels_by_type(client, headers):
    response = client.post("/api/v1/publishing/channels/seed", headers=headers)
    assert response.status_code == 200
    return {c["channel_type"]: c for c in response.json()["channels"]}


def make_storyboard(engine, tmp_path: Path, scenes: int = 2) -> str:
    now = utc_now()
    script_id, claim_id, topic_id = str(uuid4()), str(uuid4()), str(uuid4())
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        if policy:
            policy.autonomy_stopped = False
        session.add(
            TopicIdea(
                id=topic_id,
                title="Policy fixture",
                topic="space",
                angle="fixture",
                target_audience="test",
                novelty_score=0.9,
                status="SELECTED",
                created_at=now,
            )
        )
        session.add(
            FactualClaim(
                id=claim_id,
                topic_id=topic_id,
                claim_text="Fixture claim.",
                claim_type="SCIENTIFIC_FACT",
                importance="CRITICAL",
                status="SUPPORTED",
                confidence=0.99,
                created_at=now,
            )
        )
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                version=1,
                title="Policy fixture script",
                target_duration_seconds=12,
                voiceover_full_text="Fixture narration.",
                scenes_json=[
                    {
                        "scene_index": i,
                        "visual_prompt": f"Scene {i}",
                        "duration_seconds": 6.0,
                        "voiceover_segment": f"Narration {i}.",
                        "shot_type": "WIDE",
                        "transition_in": "FADE",
                        "claim_ids": [claim_id],
                    }
                    for i in range(1, scenes + 1)
                ],
                status="APPROVED",
                claim_ids_json=[claim_id],
                unverified_claim_ids_json=[],
                created_at=now,
            )
        )
    return generate_storyboard_from_script(
        engine, script_id, "MOTION_GRAPHIC", "9:16", str(uuid4())
    )["id"]


def cast(engine, storyboard_id, scene_index, character_ids):
    with Session(engine) as session, session.begin():
        scene = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id,
                StoryboardScene.scene_index == scene_index,
            )
        )
        scene.character_ids_json = character_ids


def plan(client, headers, storyboard_id):
    response = client.get(
        f"/api/v1/media/storyboards/{storyboard_id}/production-plan", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def set_production(client, headers, storyboard_id, **body):
    response = client.put(
        f"/api/v1/media/storyboards/{storyboard_id}/production", headers=headers, json=body
    )
    assert response.status_code == 200, response.text
    return response.json()


def scene_voice(the_plan, index):
    return next(s["voice"] for s in the_plan["scenes"] if s["scene_index"] == index)


def character_named(client, headers, fragment):
    characters = client.get("/api/v1/media/character-bible", headers=headers).json()["characters"]
    return next(c for c in characters if fragment in c["canonical_name"])


def add_generic_provider(engine, kind, status="ACCESS_VERIFIED"):
    """A verified non-ElevenLabs connection, as the video purpose will have one day."""
    identifier = str(uuid4())
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "settings.integration_saved", "integration", identifier, 1, {}, str(uuid4())
        )
        session.add(
            Integration(
                id=identifier,
                kind=kind,
                name=kind,
                config={},
                encrypted_secrets=vault.encrypt({"api_key": "k"}),
                secret_fields=["api_key"],
                version=1,
                status=status,
                checked_at=None,
                event_id=event.event_id,
            )
        )
    return identifier


@pytest.fixture
def studio(client, headers, elevenlabs_api):
    """One verified voice connection with two models and two voices, selected for `voice`."""
    elevenlabs_api.models.append(
        {
            "model_id": f"test-model-{uuid4()}",
            "name": "Second TTS model",
            "can_do_text_to_speech": True,
        }
    )
    identifier = connect_elevenlabs(client, headers)
    select_voice(client, headers, identifier)
    models = [m["model_id"] for m in elevenlabs_api.models]
    voices = [v["voice_id"] for v in elevenlabs_api.voices]
    set_default(client, headers, identifier, models[0], voices[0])
    return {
        "integration": identifier,
        "models": models,
        "voices": voices,
        "channels": channels_by_type(client, headers),
    }


# --------------------------------------------------------------------------- seeds


def test_channels_carry_their_policy_and_it_is_editable_data(client, headers, engine):
    channels = channels_by_type(client, headers)
    assert channels["MAIN_FACTUAL"]["production_policy"] == "FLEXIBLE"
    assert channels["OFFICE_SERIAL"]["production_policy"] == "CONSISTENCY_LOCKED"
    # The policy is a row value: the Owner can change it, and the seed never overwrites it.
    flexible = channels["OFFICE_SERIAL"]["id"]
    response = client.put(
        f"/api/v1/publishing/channels/{flexible}/production-policy",
        headers=headers,
        json={"production_policy": "FLEXIBLE"},
    )
    assert response.status_code == 200
    assert channels_by_type(client, headers)["OFFICE_SERIAL"]["production_policy"] == "FLEXIBLE"
    assert (
        client.put(
            f"/api/v1/publishing/channels/{flexible}/production-policy",
            headers=headers,
            json={"production_policy": "WHATEVER"},
        ).status_code
        == 422
    )
    assert (
        client.put(
            f"/api/v1/publishing/channels/{flexible}/production-policy",
            headers=headers,
            json={"production_defaults_json": {"voice": {"nonsense": 1}}},
        ).status_code
        == 422
    )


# --------------------------------------------------------------------------- TEST 1


def test_nexus_curiosity_picks_technology_per_video_without_touching_the_connection(
    client, headers, engine, tmp_path, studio
):
    m1, m2 = studio["models"]
    v1, v2 = studio["voices"]
    channel = studio["channels"]["MAIN_FACTUAL"]["id"]
    video_a = make_storyboard(engine, tmp_path)
    video_b = make_storyboard(engine, tmp_path)
    set_production(
        client,
        headers,
        video_a,
        channel_id=channel,
        production_overrides_json={"voice": {"model_id": m1, "voice_id": v1}},
    )
    set_production(
        client,
        headers,
        video_b,
        channel_id=channel,
        production_overrides_json={"voice": {"model_id": m2, "voice_id": v2}},
    )

    a, b = plan(client, headers, video_a), plan(client, headers, video_b)
    assert a["policy"] == "FLEXIBLE"
    assert (a["purposes"]["voice"]["model_id"], a["purposes"]["voice"]["voice_id"]) == (m1, v1)
    assert (b["purposes"]["voice"]["model_id"], b["purposes"]["voice"]["voice_id"]) == (m2, v2)
    assert a["purposes"]["voice"]["source_level"] == "episode" and a["purposes"]["voice"]["valid"]
    assert b["purposes"]["voice"]["valid"]

    # The adapters the render would use carry exactly those choices, from one connection.
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    planned_b = render_plan(engine, vault, video_b)
    adapter = planned_b["tts_for_scene"]({"scene_index": 1})
    assert (adapter.model, adapter.voice_id) == (m2, v2)
    # The Organization default and the connection are untouched.
    production = catalog(client, headers, studio["integration"])["production"]
    assert (production["model_id"], production["voice_id"]) == (m1, v1)
    with Session(engine) as session:
        assert session.get(Integration, studio["integration"]).status == "VERIFIED"


def test_flexible_channel_can_ask_for_automatic_selection_from_stored_annotations(
    client, headers, engine, tmp_path, studio
):
    m1, m2 = studio["models"]
    channel = studio["channels"]["MAIN_FACTUAL"]["id"]
    # Research annotates the second model as better and cheaper; nothing in code prefers it.
    with Session(engine) as session, session.begin():
        for row in session.scalars(
            select(ProviderResource).where(
                ProviderResource.integration_id == studio["integration"],
                ProviderResource.resource_type == "MODEL",
            )
        ):
            row.capabilities = {"quality_score": 0.9 if row.remote_id == m2 else 0.4}
            row.pricing = {"per_1k_characters_usd": 0.1 if row.remote_id == m2 else 0.3}
    video = make_storyboard(engine, tmp_path)
    set_production(
        client,
        headers,
        video,
        channel_id=channel,
        production_overrides_json={
            "voice": {"strategy": "auto", "criteria": {"weights": {"quality": 0.5, "cost": 0.5}}}
        },
    )
    voice = plan(client, headers, video)["purposes"]["voice"]
    assert voice["model_id"] == m2
    assert voice["ranking"][0]["remote_id"] == m2 and voice["ranking"][0]["annotated"]
    assert voice["valid"]
    # A locked channel refuses automatic voice choice for the same override.
    locked = studio["channels"]["OFFICE_SERIAL"]["id"]
    set_production(client, headers, video, channel_id=locked)
    voice = plan(client, headers, video)["purposes"]["voice"]
    assert voice["model_id"] == m1, "technology stays at the channel-level decision"
    assert any("Consistency-locked" in note for note in voice["notes"])


# --------------------------------------------------------------------------- TEST 2 + 4


def test_inside_the_nexus_keeps_a_locked_voice_across_episodes_and_default_changes(
    client, headers, engine, tmp_path, studio
):
    m1, m2 = studio["models"]
    v1, v2 = studio["voices"]
    integration = studio["integration"]
    channel = studio["channels"]["OFFICE_SERIAL"]["id"]
    sarah = character_named(client, headers, "Sarah")["id"]

    bound = client.put(
        f"/api/v1/media/character-bible/{sarah}/voice-binding",
        headers=headers,
        json={"integration_id": integration, "voice_id": v1, "model_id": m1, "language": "en"},
    )
    assert bound.status_code == 200, bound.text
    locked = client.put(
        f"/api/v1/media/character-bible/{sarah}/identity-locks",
        headers=headers,
        json={"voice": True, "visual": True, "personality": True, "speech_style": True},
    )
    assert locked.status_code == 200 and locked.json()["identity_locks_json"]["voice"] is True

    episodes = []
    for _ in range(3):  # episodes 1, 2 and "10"
        episode = make_storyboard(engine, tmp_path)
        cast(engine, episode, 1, [sarah])
        # Production wishes for a different voice; the lock decides otherwise.
        set_production(
            client,
            headers,
            episode,
            channel_id=channel,
            production_overrides_json={"voice": {"voice_id": v2}},
        )
        episodes.append(episode)

    # TEST 4: the Organization default voice changes for everyone else.
    set_default(client, headers, integration, m1, v2)

    for episode in episodes:
        resolved = scene_voice(plan(client, headers, episode), 1)
        assert resolved["voice_id"] == v1 and resolved["lock_applied"] is True
        assert resolved["source_level"] == "character" and resolved["character_id"] == sarah
        assert resolved["valid"]
        # A scene without her follows the hierarchy: the default is now v2, and the episode's
        # voice wish is a setting, not technology, so it is allowed but names the same v2.
        other = scene_voice(plan(client, headers, episode), 2)
        assert other["voice_id"] == v2 and other["lock_applied"] is False

    # Nexus Curiosity picks up the new default where nothing overrides it.
    flexible = make_storyboard(engine, tmp_path)
    set_production(client, headers, flexible, channel_id=studio["channels"]["MAIN_FACTUAL"]["id"])
    assert plan(client, headers, flexible)["purposes"]["voice"]["voice_id"] == v2

    # The lock cannot be bypassed by rebinding.
    rebind = client.put(
        f"/api/v1/media/character-bible/{sarah}/voice-binding",
        headers=headers,
        json={"integration_id": integration, "voice_id": v2},
    )
    assert rebind.status_code == 409 and "locked" in rebind.json()["detail"]

    # The render adapters honour the lock too.
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    planned = render_plan(engine, vault, episodes[-1])
    assert planned["tts_for_scene"]({"scene_index": 1}).voice_id == v1
    assert planned["tts_for_scene"]({"scene_index": 2}).voice_id == v2
    assert planned["plan"]["policy"] == "CONSISTENCY_LOCKED"


def test_identity_changes_go_through_proposed_testing_approved(
    client, headers, engine, tmp_path, studio
):
    m1, m2 = studio["models"]
    v1, v2 = studio["voices"]
    integration = studio["integration"]
    sarah = character_named(client, headers, "Sarah")["id"]
    client.put(
        f"/api/v1/media/character-bible/{sarah}/voice-binding",
        headers=headers,
        json={"integration_id": integration, "voice_id": v1, "model_id": m1},
    )
    client.put(
        f"/api/v1/media/character-bible/{sarah}/identity-locks",
        headers=headers,
        json={"voice": True},
    )
    episode = make_storyboard(engine, tmp_path)
    cast(engine, episode, 1, [sarah])
    set_production(client, headers, episode, channel_id=studio["channels"]["OFFICE_SERIAL"]["id"])

    proposed = client.post(
        f"/api/v1/media/character-bible/{sarah}/identity-changes",
        headers=headers,
        json={
            "field": "voice",
            "proposed_json": {"integration_id": integration, "voice_id": v2, "model_id": m2},
            "rationale": "Casting decision after the season review.",
        },
    )
    assert proposed.status_code == 201, proposed.text
    change = proposed.json()
    assert (
        change["status"] == "PROPOSED"
        and change["previous_json"]["voice_binding_json"]["voice_id"] == v1
    )
    assert character_named(client, headers, "Sarah")["consistency_status"] == "CHANGE_PENDING"
    # Still v1 while the change is open, and a second open proposal is refused.
    assert scene_voice(plan(client, headers, episode), 1)["voice_id"] == v1
    assert (
        client.post(
            f"/api/v1/media/character-bible/{sarah}/identity-changes",
            headers=headers,
            json={
                "field": "voice",
                "proposed_json": {"integration_id": integration, "voice_id": v2},
                "rationale": "again",
            },
        ).status_code
        == 409
    )

    testing = client.post(
        f"/api/v1/media/identity-changes/{change['id']}/decision",
        headers=headers,
        json={
            "status": "TESTING",
            "decided_by": "QA",
            "test_evidence_json": {"renders_compared": 3},
        },
    )
    assert testing.status_code == 200 and testing.json()["status"] == "TESTING"
    assert scene_voice(plan(client, headers, episode), 1)["voice_id"] == v1
    approved = client.post(
        f"/api/v1/media/identity-changes/{change['id']}/decision",
        headers=headers,
        json={
            "status": "APPROVED",
            "decided_by": "Director",
            "notes": "Continuity preserved in tests.",
        },
    )
    assert approved.status_code == 200 and approved.json()["decided_by"] == "Director"
    sarah_now = character_named(client, headers, "Sarah")
    assert (
        sarah_now["voice_binding_json"]["voice_id"] == v2
        and sarah_now["consistency_status"] == "CONSISTENT"
    )
    assert sarah_now["identity_locks_json"]["voice"] is True, (
        "the lock survives the approved change"
    )
    assert {f["model_id"] for f in sarah_now["approved_fallbacks_json"]} == {m1}
    assert scene_voice(plan(client, headers, episode), 1)["voice_id"] == v2
    # A decided change cannot be decided again.
    assert (
        client.post(
            f"/api/v1/media/identity-changes/{change['id']}/decision",
            headers=headers,
            json={"status": "REJECTED", "decided_by": "x"},
        ).status_code
        == 409
    )
    # A rejected change leaves the character as it was.
    rejected = client.post(
        f"/api/v1/media/character-bible/{sarah}/identity-changes",
        headers=headers,
        json={
            "field": "voice",
            "proposed_json": {"integration_id": integration, "voice_id": v1},
            "rationale": "revert?",
        },
    ).json()
    client.post(
        f"/api/v1/media/identity-changes/{rejected['id']}/decision",
        headers=headers,
        json={"status": "REJECTED", "decided_by": "Director"},
    )
    assert character_named(client, headers, "Sarah")["voice_binding_json"]["voice_id"] == v2
    assert [
        c["status"]
        for c in client.get(
            f"/api/v1/media/identity-changes?character_id={sarah}", headers=headers
        ).json()["changes"]
    ] == ["REJECTED", "APPROVED"]


# --------------------------------------------------------------------------- TEST 3


def test_a_newly_discovered_model_appears_without_overwriting_defaults_or_identities(
    client, headers, engine, tmp_path, studio, elevenlabs_api
):
    m1, m2 = studio["models"]
    v1, v2 = studio["voices"]
    integration = studio["integration"]
    sarah = character_named(client, headers, "Sarah")["id"]
    client.put(
        f"/api/v1/media/character-bible/{sarah}/voice-binding",
        headers=headers,
        json={"integration_id": integration, "voice_id": v1, "model_id": m1},
    )
    client.put(
        f"/api/v1/media/character-bible/{sarah}/identity-locks",
        headers=headers,
        json={"voice": True},
    )
    episode = make_storyboard(engine, tmp_path)
    cast(engine, episode, 1, [sarah])
    set_production(client, headers, episode, channel_id=studio["channels"]["OFFICE_SERIAL"]["id"])
    before = plan(client, headers, episode)

    new_model = f"test-model-{uuid4()}"
    elevenlabs_api.models.append(
        {"model_id": new_model, "name": "Newest TTS model", "can_do_text_to_speech": True}
    )
    refreshed = client.post(
        f"/api/v1/settings/integrations/{integration}/refresh-resources", headers=headers
    )
    assert refreshed.status_code == 200 and refreshed.json()["status"] == "VERIFIED"

    models = {m["remote_id"] for m in catalog(client, headers, integration)["models"]}
    assert new_model in models and {m1, m2} <= models
    production = catalog(client, headers, integration)["production"]
    assert (production["model_id"], production["voice_id"]) == (m1, v1), (
        "defaults are not replaced by discovery"
    )
    sarah_now = character_named(client, headers, "Sarah")
    assert sarah_now["voice_binding_json"] == {
        "integration_id": integration,
        "voice_id": v1,
        "model_id": m1,
        "voice_settings": {},
        "language": None,
        "pronunciation_rules": [],
    }
    assert scene_voice(plan(client, headers, episode), 1) == scene_voice(before, 1)

    # The new model reaches the locked character only through an approval; an episode
    # wish is not enough.
    set_production(
        client, headers, episode, production_overrides_json={"voice": {"model_id": new_model}}
    )
    resolved = scene_voice(plan(client, headers, episode), 1)
    assert resolved["model_id"] == m1 and resolved["voice_id"] == v1
    approved = client.post(
        f"/api/v1/media/character-bible/{sarah}/approved-models",
        headers=headers,
        json={"integration_id": integration, "model_id": new_model, "decided_by": "Director"},
    )
    assert approved.status_code == 200
    # Approved technology is chosen at channel/series level on a locked channel.
    channel = studio["channels"]["OFFICE_SERIAL"]["id"]
    client.put(
        f"/api/v1/publishing/channels/{channel}/production-policy",
        headers=headers,
        json={"series_rules_json": {"season-1": {"voice": {"model_id": new_model}}}},
    )
    set_production(client, headers, episode, series_key="season-1", production_overrides_json={})
    resolved = scene_voice(plan(client, headers, episode), 1)
    assert (resolved["model_id"], resolved["voice_id"]) == (new_model, v1)
    assert any("approved fallbacks" in note for note in resolved["notes"])


# --------------------------------------------------------------------------- TEST 5


def test_video_technology_evolves_freely_on_the_flexible_channel_and_by_approval_on_the_locked_one(
    client, headers, engine, tmp_path, studio
):
    video_provider = add_generic_provider(engine, "openai_media")
    flexible, locked = (
        studio["channels"]["MAIN_FACTUAL"]["id"],
        studio["channels"]["OFFICE_SERIAL"]["id"],
    )
    curiosity = make_storyboard(engine, tmp_path)
    nexus = make_storyboard(engine, tmp_path)
    wish = {"video": {"integration_id": video_provider, "model_id": "video-model-b"}}
    set_production(client, headers, curiosity, channel_id=flexible, production_overrides_json=wish)
    set_production(client, headers, nexus, channel_id=locked, production_overrides_json=wish)

    assert plan(client, headers, curiosity)["purposes"]["video"]["model_id"] == "video-model-b"
    assert plan(client, headers, curiosity)["purposes"]["video"]["valid"]
    nexus_video = plan(client, headers, nexus)["purposes"]["video"]
    assert nexus_video["model_id"] is None and not nexus_video["valid"]
    assert any("Consistency-locked" in note for note in nexus_video["notes"])

    # After QA the Director approves it for the series: the channel/series level carries it.
    client.put(
        f"/api/v1/publishing/channels/{locked}/production-policy",
        headers=headers,
        json={"production_defaults_json": wish},
    )
    approved = plan(client, headers, nexus)["purposes"]["video"]
    assert (
        approved["model_id"] == "video-model-b"
        and approved["source_level"] == "channel"
        and approved["valid"]
    )


def test_organization_default_can_refuse_overrides_but_locks_still_win(
    client, headers, engine, tmp_path, studio
):
    m1, m2 = studio["models"]
    v1, v2 = studio["voices"]
    set_default(client, headers, studio["integration"], m1, v1, allow=False)
    video = make_storyboard(engine, tmp_path)
    set_production(
        client,
        headers,
        video,
        channel_id=studio["channels"]["MAIN_FACTUAL"]["id"],
        production_overrides_json={"voice": {"voice_id": v2}},
    )
    voice = plan(client, headers, video)["purposes"]["voice"]
    assert voice["voice_id"] == v1 and voice["source_level"] == "organization"
    assert any("does not allow" in note for note in voice["notes"])


# --------------------------------------------------------------------------- TEST 6 + 7


def test_existing_integrations_and_discovery_survive_and_nothing_is_duplicated(
    client, headers, engine, studio, elevenlabs_api, connect_youtube
):
    integration = studio["integration"]
    assert character_named(client, headers, "Sarah")["consistency_status"] == "UNVERIFIED"
    youtube_id, _ = connect_youtube(
        name="Channel one", channel_id="UC-test-one", title="Channel one"
    )

    # Discovery still works through the one existing path, and the key is still stored.
    refreshed = client.post(
        f"/api/v1/settings/integrations/{integration}/refresh-resources", headers=headers
    )
    assert refreshed.status_code == 200 and refreshed.json()["discovery_status"] == "READY"
    listing = client.get("/api/v1/youtube/connections", headers=headers).json()
    assert any(c["id"] == youtube_id and c["status"] == "CONNECTED" for c in listing["connections"])

    with Session(engine) as session:
        assert session.get(Integration, integration).status == "VERIFIED"
        resources = session.scalars(
            select(ProviderResource).where(ProviderResource.integration_id == integration)
        ).all()
        assert len(resources) == len(elevenlabs_api.models) + len(elevenlabs_api.voices), (
            "one inventory, no parallel registry"
        )
        assert (
            session.scalars(
                select(MediaProductionConfig).where(
                    MediaProductionConfig.integration_id == integration
                )
            )
            .all()
            .__len__()
            == 1
        )
        assert (
            session.scalar(
                select(CharacterBible).where(CharacterBible.canonical_name.like("Sarah%"))
            )
            is not None
        )

    # The policy module reuses the discovery validator rather than shipping its own.
    from app.integrations import discovery
    from app.media import production_policy

    assert production_policy.production_resource is discovery.production_resource


# --------------------------------------------------------------------------- TEST 5, video


def connect_runway(client, headers):
    identifier = str(uuid4())
    response = client.put(
        f"/api/v1/settings/integrations/{identifier}",
        headers=headers,
        json={
            "kind": "runway",
            "name": "Studio video account",
            "secrets": {"api_key": f"k-{uuid4()}"},
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "VERIFIED"
    return identifier


def select_video(client, headers, identifier, default_model):
    response = client.put(
        "/api/v1/settings/selections/video",
        headers=headers,
        json={"integration_id": identifier, "expected_version": 0},
    )
    assert response.status_code == 200, response.text
    response = client.put(
        f"/api/v1/settings/integrations/{identifier}/production",
        headers=headers,
        json={"model_id": default_model, "expected_version": 0},
    )
    assert response.status_code == 200, response.text


def scene_video(the_plan, index):
    return next(s["video"] for s in the_plan["scenes"] if s["scene_index"] == index)


def test_runway_models_are_picked_per_video_on_the_flexible_channel_and_per_series_on_the_locked(
    client, headers, engine, tmp_path, studio, runway_api
):
    runway = connect_runway(client, headers)
    video_a, video_b = runway_api.video_models
    select_video(client, headers, runway, video_a)
    flexible = studio["channels"]["MAIN_FACTUAL"]["id"]
    locked = studio["channels"]["OFFICE_SERIAL"]["id"]

    # Nexus Curiosity: the default is a fallback; a video may pick any discovered video model.
    plain = make_storyboard(engine, tmp_path)
    set_production(client, headers, plain, channel_id=flexible)
    resolved = plan(client, headers, plain)["purposes"]["video"]
    assert (resolved["model_id"], resolved["source_level"], resolved["valid"]) == (
        video_a,
        "organization",
        True,
    )
    special = make_storyboard(engine, tmp_path)
    wish = {"video": {"model_id": video_b}}
    set_production(client, headers, special, channel_id=flexible, production_overrides_json=wish)
    resolved = plan(client, headers, special)["purposes"]["video"]
    assert (resolved["model_id"], resolved["source_level"], resolved["valid"]) == (
        video_b,
        "episode",
        True,
    )
    # ...and a scene may differ from its video; the render plan builds one adapter per choice.
    set_production(
        client, headers, special, scene_overrides={"2": {"video": {"model_id": video_a}}}
    )
    the_plan = plan(client, headers, special)
    assert scene_video(the_plan, 1)["model_id"] == video_b
    assert scene_video(the_plan, 2)["model_id"] == video_a
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    planned = render_plan(engine, vault, special)
    assert planned["video_for_scene"]({"scene_index": 1}).model == video_b
    assert planned["video_for_scene"]({"scene_index": 2}).model == video_a
    assert planned["video_for_scene"]({"scene_index": 2}).model_metadata["tasks"] == [
        "image_to_video",
        "text_to_video",
    ]
    # Not a model the account has that makes stills, and not one nobody discovered.
    for wrong in (runway_api.image_model, "gen-imagined"):
        set_production(
            client, headers, special, production_overrides_json={"video": {"model_id": wrong}}
        )
        assert not plan(client, headers, special)["purposes"]["video"]["valid"]

    # Inside The Nexus: an episode wish is ignored; the series decides, once approved there.
    nexus = make_storyboard(engine, tmp_path)
    set_production(client, headers, nexus, channel_id=locked, production_overrides_json=wish)
    resolved = plan(client, headers, nexus)["purposes"]["video"]
    assert resolved["model_id"] == video_a and resolved["valid"]
    assert any("Consistency-locked" in note for note in resolved["notes"])
    response = client.put(
        f"/api/v1/publishing/channels/{locked}/production-policy",
        headers=headers,
        json={"series_rules_json": {"inside-the-nexus": {"video": {"model_id": video_b}}}},
    )
    assert response.status_code == 200, response.text
    set_production(client, headers, nexus, series_key="inside-the-nexus")
    resolved = plan(client, headers, nexus)["purposes"]["video"]
    assert (resolved["model_id"], resolved["source_level"], resolved["valid"]) == (
        video_b,
        "series",
        True,
    )
    # The ElevenLabs default and its discovery are untouched by a second discovered kind.
    assert plan(client, headers, nexus)["purposes"]["voice"]["valid"]
    with Session(engine) as session:
        assert session.get(Integration, studio["integration"]).status == "VERIFIED"
        assert (
            session.get(MediaProductionConfig, studio["integration"]).model_id
            == (studio["models"][0])
        )


def test_a_locked_look_accepts_only_video_models_approved_for_the_character(
    client, headers, engine, tmp_path, studio, runway_api
):
    runway = connect_runway(client, headers)
    video_a, video_b = runway_api.video_models
    select_video(client, headers, runway, video_a)
    sarah = character_named(client, headers, "Sarah")["id"]
    locked = client.put(
        f"/api/v1/media/character-bible/{sarah}/identity-locks",
        headers=headers,
        json={"visual": True},
    )
    assert locked.status_code == 200, locked.text
    episode = make_storyboard(engine, tmp_path)
    set_production(client, headers, episode, channel_id=studio["channels"]["OFFICE_SERIAL"]["id"])
    cast(engine, episode, 2, [sarah])

    the_plan = plan(client, headers, episode)
    blocked = scene_video(the_plan, 2)
    assert not blocked["valid"] and blocked["lock_applied"] and blocked["character_id"] == sarah
    assert any("Visual identity locked" in note for note in blocked["notes"])
    free = scene_video(the_plan, 1)
    assert free["valid"] and not free["lock_applied"] and free["model_id"] == video_a
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    planned = render_plan(engine, vault, episode)
    assert planned["video_for_scene"]({"scene_index": 2}) is None
    assert planned["video_for_scene"]({"scene_index": 1}).model == video_a

    # A consistency test passed: the Director approves the model for her. Her look is unchanged.
    approved = client.post(
        f"/api/v1/media/character-bible/{sarah}/approved-models",
        headers=headers,
        json={"integration_id": runway, "model_id": video_a, "decided_by": "Director"},
    )
    assert approved.status_code == 200, approved.text
    allowed = scene_video(plan(client, headers, episode), 2)
    assert allowed["valid"] and allowed["model_id"] == video_a and allowed["lock_applied"]
    assert render_plan(engine, vault, episode)["video_for_scene"]({"scene_index": 2}).model == (
        video_a
    )
    # A newer model must be approved for her too, even at series level.
    client.put(
        f"/api/v1/publishing/channels/{studio['channels']['OFFICE_SERIAL']['id']}/production-policy",
        headers=headers,
        json={"production_defaults_json": {"video": {"model_id": video_b}}},
    )
    again = scene_video(plan(client, headers, episode), 2)
    assert not again["valid"] and again["model_id"] == video_b
    assert scene_video(plan(client, headers, episode), 1)["valid"]


# --------------------------------------------------------------------- what the studio is for


def test_a_premium_studio_ranks_the_best_picture_first_and_the_frame_decides_ties(engine):
    """The Owner's instruction — "Nu facem rabat de la cheltuieli" — is a weighting, and it
    had none: an even split over quality, cost, speed and reliability had the ranking (and
    the steward) recommending the cheapest model twice. A model whose own contract cannot
    fill 1080x1920 never outranks one that can, whatever it costs."""
    from app.media.production_policy import (
        PRIORITY_WEIGHTS,
        delivers_studio_frame,
        rank_candidates,
    )
    from app.services import utc_now

    integration_id = add_generic_provider(engine, "runway")
    with Session(engine) as session, session.begin():
        for remote_id, quality, price, ratios in (
            ("beautiful_tall", 0.9, 0.03, ["1080:1920", "720:1280"]),
            ("cheap_tall", 0.6, 0.005, ["1080:1920"]),
            ("cheap_short", 0.95, 0.004, ["720:1280"]),
        ):
            session.add(
                ProviderResource(
                    id=str(uuid4()),
                    integration_id=integration_id,
                    resource_type="MODEL",
                    remote_id=remote_id,
                    name=remote_id,
                    api_metadata={
                        "tasks": ["image_to_video", "text_to_video"],
                        "ratios": {"text_to_video": ratios, "image_to_video": ratios},
                        "needs_references": {"text_to_video": False, "image_to_video": False},
                    },
                    api_available=True,
                    last_seen_at=utc_now(),
                    pricing={"per_second_usd": price, "unit": "per second of video"},
                    capabilities={"quality_score": quality, "reliability_score": 0.8},
                    metadata_version=1,
                )
            )

    with Session(engine) as session:
        premium = rank_candidates(session, integration_id, "MODEL", None, "video")
        thrifty = rank_candidates(
            session, integration_id, "MODEL", {"priority": "thrifty"}, "video"
        )
    # Premium is the studio's standing default: the best picture that fills the frame wins.
    assert premium[0]["remote_id"] == "beautiful_tall"
    # The cheapest model of all cannot fill the frame, so it is last whatever the priority.
    assert premium[-1]["remote_id"] == "cheap_short"
    assert thrifty[-1]["remote_id"] == "cheap_short"
    # And thrift does change the order among the models that can fill it.
    assert thrifty[0]["remote_id"] == "cheap_tall"
    assert PRIORITY_WEIGHTS["premium"]["quality"] > PRIORITY_WEIGHTS["premium"]["cost"]
    assert delivers_studio_frame({"tasks": ["text_to_video"]}, "video") is True
