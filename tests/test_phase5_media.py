"""Phase 5 Media Production & Milestone 2 test suite.

Tests:
- Character Bible configuration and default seeding.
- Storyboard generation from approved script drafts (Strict Content Gate).
- Rejection of unapproved scripts or scripts with unverified claims.
- Autonomy stop gating on storyboarding.
- Deterministic Visual and TTS media adapters.
- Subtitle SRT generation and timestamp synchronization.
- End-to-end video assembly and SHA-256 provenance calculation.
- Quality Control (QC) gate: Technical, Factual, Character, and Rights checks.
- Media REST API endpoints and Owner authentication.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from app.factual.models import FactualClaim, ScriptDraft, TopicIdea
from app.factual.services import FactualGateError
from app.media.assembler import RenderEngineUnavailable, assemble_video_job
from app.media.models import MediaAsset, VideoRenderJob
from app.media.qc import evaluate_media_qc
from app.media.services import (
    generate_storyboard_from_script,
    list_character_bibles,
    seed_default_character_bibles,
)
from app.media.toolchain import find_ffmpeg
from app.models import OwnerPolicy
from app.providers.deterministic_media import (
    DeterministicTTSAdapter,
    DeterministicVisualAdapter,
)
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

# Skip when *the studio* cannot find an encoder, not when PATH happens not to carry one: the
# Owner's ffmpeg is configured in .env and is not on PATH, so these tests were skipping while a
# real encoder sat ready to use.
requires_ffmpeg = pytest.mark.skipif(
    find_ffmpeg() is None,
    reason=(
        "FFmpeg not installed; the studio refuses to fake a render, so there is nothing to assert"
    ),
)


def test_character_bible_seeding_and_retrieval(engine):
    # 1. Seed defaults
    seeded = seed_default_character_bibles(engine)
    assert seeded == 8  # 8 studio characters: the seven producers and the Accountant

    # 2. List characters
    chars = list_character_bibles(engine)
    assert len(chars) == 8

    sarah = next(c for c in chars if "Sarah" in c["canonical_name"])
    assert sarah["voice_profile_json"]["voice_id"] == "sarah_executive"
    assert "navy" in sarah["outfit_desc"].lower()
    assert "athletic" in sarah["forbidden_deviations"].lower()

    # Re-seeding when already populated should be idempotent (add 0)
    assert seed_default_character_bibles(engine) == 0


def test_every_character_carries_persona_speech_expressions_and_behaviour(engine):
    """Look and voice were stored; who the character is was not. A story engine that cannot
    read a speaking style from the bible invents one per episode, which is what the persona
    specification forbids."""
    seed_default_character_bibles(engine)

    for character in list_character_bibles(engine):
        personality = character["personality_json"]
        speech = character["speech_style_json"]
        assert personality["traits"] and personality["values"]
        assert personality["conflict_style"] and personality["humor"]
        assert speech["register"] and speech["cadence"] and speech["language"]
        expressions = character["expressions_json"]
        assert expressions["greeting"] and expressions["agreement"]
        assert expressions["disagreement"] and expressions["under_pressure"]
        behaviour = character["behavior_json"]
        assert behaviour["work_rituals"] and behaviour["likes"] and behaviour["dislikes"]

    elena = next(c for c in list_character_bibles(engine) if "Elena" in c["canonical_name"])
    assert elena["speech_style_json"]["register"] == "checklist"
    assert "not supported" in elena["expressions_json"]["disagreement"]


def test_reference_slots_are_declared_empty_rather_than_filled_with_invented_assets(engine):
    """Doc 24 wants a portrait and body references. None have been produced, so every slot is
    declared and null; a description standing in for a missing image would let continuity QC
    believe a reference exists."""
    seed_default_character_bibles(engine)

    for character in list_character_bibles(engine):
        slots = character["reference_assets_json"]
        assert set(slots) == {"portrait", "full_body", "front", "side", "back"}
        assert all(value is None for value in slots.values())


def test_an_entry_seeded_before_the_persona_fields_is_completed_but_never_overwritten(engine):
    """Databases seeded by an earlier version hold the canonical seven with empty persona
    fields. The seed completes them once; an Owner's edit survives the next read."""
    from app.media.models import CharacterBible
    from sqlalchemy import select as sa_select

    seed_default_character_bibles(engine)
    with Session(engine) as session, session.begin():
        rows = session.scalars(sa_select(CharacterBible)).all()
        for row in rows:
            row.personality_json = {}
            row.speech_style_json = {}
            row.expressions_json = {}
            row.behavior_json = {}
            row.reference_assets_json = {}
        edited = next(r for r in rows if "Lyra" in r.canonical_name)
        edited.expressions_json = {"greeting": "Owner's own line."}

    assert seed_default_character_bibles(engine) > 0

    characters = {c["canonical_name"]: c for c in list_character_bibles(engine)}
    assert characters["Kael Video Editor"]["speech_style_json"]["register"] == "control room"
    lyra = next(c for c in characters.values() if "Lyra" in c["canonical_name"])
    assert lyra["expressions_json"] == {"greeting": "Owner's own line."}
    assert lyra["personality_json"]["traits"], "empty fields beside an edited one are filled"

    # And a third read changes nothing further.
    assert seed_default_character_bibles(engine) == 0


def test_deterministic_visual_and_tts_adapters():
    visual_adapter = DeterministicVisualAdapter()
    tts_adapter = DeterministicTTSAdapter()

    # 1. Test Visual Card generation
    img_res = asyncio.run(
        visual_adapter.generate_image(
            "Executive Sarah explaining quarterly AI studio metrics",
            width=1080,
            height=1920,
            extra={"title": "TEST SHORT", "scene_index": 1},
        )
    )
    assert img_res.format == "svg"
    assert img_res.width == 1080
    assert img_res.height == 1920
    assert len(img_res.image_bytes) > 100
    assert b"<svg" in img_res.image_bytes
    assert b"1080" in img_res.image_bytes

    # 2. Test TTS voiceover generation
    tts_res = asyncio.run(
        tts_adapter.synthesize(
            "Artificial intelligence media studios operate with full observability."
        )
    )
    assert tts_res.format == "wav"
    assert tts_res.duration_seconds >= 2.0
    assert len(tts_res.audio_bytes) > 44  # Valid WAV header + samples
    assert tts_res.audio_bytes[:4] == b"RIFF"
    assert tts_res.audio_bytes[8:12] == b"WAVE"
    assert len(tts_res.word_timings) > 0


def test_storyboard_generation_enforces_content_gate(engine):
    now = utc_now()
    corr_id = str(uuid4())
    script_id = str(uuid4())
    claim_id = str(uuid4())

    with Session(engine) as session, session.begin():
        # Clear autonomy stop for testing active generation
        policy = session.get(OwnerPolicy, 1)
        if policy:
            policy.autonomy_stopped = False

        # Create topic
        topic = TopicIdea(
            id=str(uuid4()),
            title="The Quantum Computing Breakthrough",
            topic="quantum_computing",
            angle="Why qubit stability changes everything",
            target_audience="tech_enthusiasts",
            novelty_score=0.92,
            status="SELECTED",
            created_at=now,
        )
        session.add(topic)

        # Create verified claim
        claim = FactualClaim(
            id=claim_id,
            topic_id=topic.id,
            claim_text="Qubit coherence reached 100 microseconds.",
            claim_type="SCIENTIFIC_FACT",
            importance="CRITICAL",
            status="SUPPORTED",
            confidence=0.98,
            created_at=now,
        )
        session.add(claim)

        # 1. Script in DRAFT status (not approved yet)
        draft_script = ScriptDraft(
            id=script_id,
            topic_id=topic.id,
            version=1,
            title="Quantum Leap",
            target_duration_seconds=45,
            voiceover_full_text="Scientists achieved breakthrough qubit coherence in lab tests.",
            scenes_json=[
                {
                    "scene_index": 1,
                    "visual_prompt": "Laboratory cryogenic dilution refrigerator glowing blue",
                    "duration_seconds": 6.0,
                    "voiceover_segment": (
                        "Scientists achieved breakthrough qubit coherence in lab tests."
                    ),
                    "shot_type": "WIDE",
                    "transition_in": "FADE",
                    "claim_ids": [claim_id],
                }
            ],
            status="DRAFT",
            claim_ids_json=[claim_id],
            unverified_claim_ids_json=[],
            created_at=now,
        )
        session.add(draft_script)

    # Attempting to storyboard a DRAFT script must fail with FactualGateError
    with pytest.raises(FactualGateError, match="must be 'APPROVED'"):
        generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", corr_id)

    # 2. Approve the script
    with Session(engine) as session, session.begin():
        s = session.get(ScriptDraft, script_id)
        s.status = "APPROVED"

    # Now storyboard generation succeeds
    sb = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", corr_id)
    assert sb["title"] == "Storyboard: Quantum Leap"
    assert sb["aspect_ratio"] == "9:16"
    assert sb["status"] == "APPROVED"
    assert len(sb["scenes"]) == 1
    assert sb["scenes"][0]["shot_type"] == "WIDE"
    assert sb["scenes"][0]["claim_ids_json"] == [claim_id]


def test_storyboard_blocked_when_autonomy_stopped(engine):
    now = utc_now()
    corr_id = str(uuid4())
    script_id = str(uuid4())

    with Session(engine) as session, session.begin():
        # Ensure autonomy stop is active
        policy = session.get(OwnerPolicy, 1)
        if policy:
            policy.autonomy_stopped = True

        topic = TopicIdea(
            id=str(uuid4()),
            title="Blocked Test Topic",
            topic="test",
            angle="test",
            target_audience="general",
            novelty_score=0.8,
            status="SELECTED",
            created_at=now,
        )
        session.add(topic)

        script = ScriptDraft(
            id=script_id,
            topic_id=topic.id,
            version=1,
            title="Blocked Script",
            target_duration_seconds=30,
            voiceover_full_text="This cannot run.",
            scenes_json=[],
            status="APPROVED",
            claim_ids_json=[],
            unverified_claim_ids_json=[],
            created_at=now,
        )
        session.add(script)

    with pytest.raises(FactualGateError, match="Global autonomy stop is active"):
        generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", corr_id)


def _seeded_storyboard(engine, tmp_path: Path) -> tuple[str, str]:
    """Create an approved script with a SUPPORTED claim and return (storyboard_id, claim_id)."""
    now = utc_now()
    corr_id = str(uuid4())
    script_id = str(uuid4())
    claim_id = str(uuid4())
    topic_id = str(uuid4())

    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        if policy:
            policy.autonomy_stopped = False
        session.add(
            TopicIdea(
                id=topic_id,
                title="Render fixture",
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
                claim_text="Fixture claim used by render tests.",
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
                title="Render fixture script",
                target_duration_seconds=12,
                voiceover_full_text="Fixture narration for the render pipeline.",
                scenes_json=[
                    {
                        "scene_index": i,
                        "visual_prompt": f"Fixture scene {i}",
                        "duration_seconds": 6.0,
                        "voiceover_segment": f"Fixture narration segment {i}.",
                        "shot_type": "WIDE",
                        "transition_in": "FADE",
                        "claim_ids": [claim_id],
                    }
                    for i in (1, 2)
                ],
                status="APPROVED",
                claim_ids_json=[claim_id],
                unverified_claim_ids_json=[],
                created_at=now,
            )
        )

    sb = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", corr_id)
    return sb["id"], claim_id


@requires_ffmpeg
def test_end_to_end_assembly_provenance_and_qc(engine, tmp_path: Path):
    now = utc_now()
    corr_id = str(uuid4())
    script_id = str(uuid4())
    claim_id = str(uuid4())

    with Session(engine) as session, session.begin():
        # Clear autonomy stop
        policy = session.get(OwnerPolicy, 1)
        if policy:
            policy.autonomy_stopped = False

        topic = TopicIdea(
            id=str(uuid4()),
            title="Mars Rover Discovery",
            topic="space",
            angle="Ancient riverbeds identified",
            target_audience="science_lovers",
            novelty_score=0.95,
            status="SELECTED",
            created_at=now,
        )
        session.add(topic)

        claim = FactualClaim(
            id=claim_id,
            topic_id=topic.id,
            claim_text="Perseverance found sediment consistent with an ancient river delta.",
            claim_type="SCIENTIFIC_FACT",
            importance="CRITICAL",
            status="SUPPORTED",
            confidence=0.99,
            created_at=now,
        )
        session.add(claim)

        script = ScriptDraft(
            id=script_id,
            topic_id=topic.id,
            version=1,
            title="Riverbeds on Mars",
            target_duration_seconds=30,
            voiceover_full_text=(
                "Perseverance rover has uncovered conclusive sediment layers "
                "from an ancient Martian lake."
            ),
            scenes_json=[
                {
                    "scene_index": 1,
                    "visual_prompt": (
                        "Red Martian landscape showing layered sedimentary rock strata"
                    ),
                    "duration_seconds": 6.0,
                    "voiceover_segment": (
                        "Perseverance rover has uncovered conclusive sediment layers."
                    ),
                    "shot_type": "WIDE",
                    "transition_in": "FADE",
                    "claim_ids": [claim_id],
                },
                {
                    "scene_index": 2,
                    "visual_prompt": "Close-up of robotic rover arm drilling into delta sandstone",
                    "duration_seconds": 6.0,
                    "voiceover_segment": (
                        "Evidence points directly to a long-lived ancient river delta."
                    ),
                    "shot_type": "CLOSE_UP",
                    "transition_in": "ZOOM",
                    "claim_ids": [claim_id],
                },
            ],
            status="APPROVED",
            claim_ids_json=[claim_id],
            unverified_claim_ids_json=[],
            created_at=now,
        )
        session.add(script)

    # 1. Generate Storyboard
    sb = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", corr_id)
    assert sb["total_scenes"] == 2

    # 2. Run Video Assembly
    storage_root = tmp_path / "media_storage"
    render_res = assemble_video_job(engine, sb["id"], corr_id, storage_root=storage_root)

    assert render_res["output_asset_id"] is not None
    assert render_res["duration_seconds"] == 12.0
    assert render_res["file_size_bytes"] > 0

    # 3. Verify SHA-256 Provenance Digest
    provenance_hash = render_res["provenance_hash"]
    assert len(provenance_hash) == 64
    int(provenance_hash, 16)  # Valid hex

    # 4. Evaluate Quality Control (QC). Technical checks are measured from the encoded file.
    qc_res = evaluate_media_qc(engine, render_res["output_asset_id"], corr_id)
    tech = qc_res["checks_json"]["technical_qc"]
    assert tech["passed"] is True, tech
    assert (tech["measured_width"], tech["measured_height"]) == (1080, 1920)
    assert tech["provenance_hash_verified"] is True
    assert tech["video_codec"] == "h264"
    assert qc_res["checks_json"]["factual_qc"]["passed"] is True
    assert qc_res["checks_json"]["rights_qc"]["passed"] is True
    # Character drift is not implemented and must not be reported as a passing check.
    assert qc_res["checks_json"]["character_drift_qc"]["status"] == "NOT_IMPLEMENTED"
    # Visuals are locally generated placeholder frames, so the asset is NOT publishable.
    assert qc_res["checks_json"]["content_source_qc"]["passed"] is False
    assert qc_res["status"] == "FAILED"
    assert any("placeholder" in r for r in qc_res["failure_reasons_json"])


def test_render_without_encoder_fails_and_records_no_asset(engine, tmp_path: Path, monkeypatch):
    """No encoder must mean no asset: never a stand-in file that later gates can pass."""
    monkeypatch.setattr("app.media.assembler.resolve_ffmpeg_path", lambda custom=None: None)
    monkeypatch.delenv("STUDIO_FFMPEG_PATH", raising=False)

    sb_id, _ = _seeded_storyboard(engine, tmp_path)
    with pytest.raises(RenderEngineUnavailable):
        assemble_video_job(engine, sb_id, str(uuid4()), storage_root=tmp_path / "media")

    with Session(engine) as session:
        assert session.scalars(select(MediaAsset)).all() == []
        jobs = session.scalars(select(VideoRenderJob)).all()
        assert [j.status for j in jobs] == ["FAILED"]


@requires_ffmpeg
def test_qc_fails_if_claim_is_refuted(engine, tmp_path: Path):
    now = utc_now()
    corr_id = str(uuid4())
    script_id = str(uuid4())
    claim_id = str(uuid4())

    with Session(engine) as session, session.begin():
        # Clear autonomy stop
        policy = session.get(OwnerPolicy, 1)
        if policy:
            policy.autonomy_stopped = False

        topic = TopicIdea(
            id=str(uuid4()),
            title="Debunked Topic",
            topic="debunk",
            angle="Unverified mystery",
            target_audience="general",
            novelty_score=0.7,
            status="SELECTED",
            created_at=now,
        )
        session.add(topic)

        claim = FactualClaim(
            id=claim_id,
            topic_id=topic.id,
            claim_text="A perpetual motion device was constructed.",
            claim_type="SCIENTIFIC_FACT",
            importance="CRITICAL",
            status="SUPPORTED",  # initially supported to pass storyboard
            confidence=0.9,
            created_at=now,
        )
        session.add(claim)

        script = ScriptDraft(
            id=script_id,
            topic_id=topic.id,
            version=1,
            title="Perpetual Motion Claim",
            target_duration_seconds=20,
            voiceover_full_text="New perpetual motion engine claims zero energy loss.",
            scenes_json=[
                {
                    "scene_index": 1,
                    "visual_prompt": "Spinning wheel diagram",
                    "duration_seconds": 12.0,
                    "voiceover_segment": "New perpetual motion engine claims zero energy loss.",
                    "shot_type": "MEDIUM",
                    "transition_in": "CUT",
                    "claim_ids": [claim_id],
                }
            ],
            status="APPROVED",
            claim_ids_json=[claim_id],
            unverified_claim_ids_json=[],
            created_at=now,
        )
        session.add(script)

    sb = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", corr_id)
    render_res = assemble_video_job(engine, sb["id"], corr_id, storage_root=tmp_path / "media")

    # Now simulate fact checker refuting the claim before publication
    with Session(engine) as session, session.begin():
        c = session.get(FactualClaim, claim_id)
        c.status = "REFUTED"

    # QC must detect the refuted claim and FAIL
    qc_res = evaluate_media_qc(engine, render_res["output_asset_id"], corr_id)
    assert qc_res["status"] == "FAILED"
    assert qc_res["score"] < 1.0
    assert qc_res["checks_json"]["factual_qc"]["passed"] is False
    assert any("REFUTED" in r for r in qc_res["failure_reasons_json"])


def test_media_api_routes_with_owner_auth(client, headers):
    # 1. Test unauthenticated request rejected
    res = client.get("/api/v1/media/character-bible")
    assert res.status_code == 401

    # 2. Test authenticated Character Bible listing
    res = client.get("/api/v1/media/character-bible", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "characters" in data
    assert len(data["characters"]) >= 7

    # 3. Test Storyboard list
    res = client.get("/api/v1/media/storyboards", headers=headers)
    assert res.status_code == 200
    assert "storyboards" in res.json()
