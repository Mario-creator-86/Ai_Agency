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
import math
from pathlib import Path
from uuid import uuid4

import pytest
from app.factual.models import FactualClaim, ScriptDraft, TopicIdea
from app.factual.services import FactualGateError
from app.media.assembler import RenderEngineUnavailable, assemble_video_job
from app.media.models import CharacterBible, MediaAsset, VideoRenderJob
from app.media.qc import evaluate_media_qc
from app.media.services import (
    generate_storyboard_from_script,
    list_character_bibles,
    seed_default_character_bibles,
)
from app.media.toolchain import find_ffmpeg, has_filter
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

    with pytest.raises(FactualGateError, match="Autonomia studioului este oprită"):
        generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", corr_id)


def _seeded_storyboard(engine, tmp_path: Path, scenes: int = 2) -> tuple[str, str]:
    """Create an approved script with a SUPPORTED claim and return (storyboard_id, claim_id).

    `scenes` is how many the script plans; a render that is stopped part way through needs a
    plan longer than what it managed, or the attempt and the plan cannot be told apart.
    """
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
                    for i in range(1, scenes + 1)
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


# ------------------------------------------------------------- captions and loudness
# Measured before this work: captions.srt was written beside the render and never muxed or
# burnt in; nothing normalised loudness; quality control had no audio and no caption check
# although 08_VIDEO_PIPELINE.md lists both; and a scene whose motion model refused became a
# slow push recorded only in a note, which no gate read.


def _words(text: str) -> list[str]:
    return [w for w in "".join(c.lower() if c.isalnum() else " " for c in text).split() if w]


def test_captions_are_cards_of_two_to_five_words_timed_by_character_share():
    """2026-10-01: a cue is a card of two to five words, never a whole sentence. Without the
    voice's own word timing the scene's spoken time is shared by the cards' characters."""
    from app.media.assembler import (
        CAPTION_LINE_CHARS,
        CAPTION_MAX_LINES,
        CAPTION_MAX_WORDS,
        CAPTION_MIN_WORDS,
        caption_cues,
    )

    first = "Perseverance found layered rock near the old crater. It points to a river delta."
    scenes = [
        {
            "scene_index": 1,
            "duration_seconds": 6.0,
            "audio_seconds": 5.0,
            "voiceover_segment": first,
        },
        {
            "scene_index": 2,
            "duration_seconds": 6.0,
            "audio_seconds": 4.0,
            "voiceover_segment": "The evidence is conclusive.",
        },
    ]
    cues = caption_cues(scenes)
    assert (CAPTION_MIN_WORDS, CAPTION_MAX_WORDS) == (2, 5)
    for cue in cues:
        words = " ".join(cue["lines"]).split()
        assert CAPTION_MIN_WORDS <= len(words) <= CAPTION_MAX_WORDS, cue
        assert 1 <= len(cue["lines"]) <= CAPTION_MAX_LINES
        assert all(len(line) <= CAPTION_LINE_CHARS for line in cue["lines"])
        assert cue["end"] > cue["start"]
        assert cue["timing"] == "character_share"
        # A sentence ends a card: no card runs on past a full stop.
        assert not any(word.endswith(".") for word in words[:-1]), cue
    # Nothing is lost or reordered.
    said = " ".join(scene["voiceover_segment"] for scene in scenes)
    assert _words(" ".join(" ".join(c["lines"]) for c in cues)) == _words(said)
    # Scene one's words are up from 0.0 until its recording ends at 5.0, scene two's from its
    # own start at 6.0 for its 4.0 seconds; the cards follow each other with no gap.
    one = [c for c in cues if c["scene_index"] == 1]
    two = [c for c in cues if c["scene_index"] == 2]
    assert one[0]["start"] == 0.0 and one[-1]["end"] == pytest.approx(5.0, abs=0.001)
    assert two[0]["start"] == pytest.approx(6.0) and two[-1]["end"] == pytest.approx(10.0)
    for before, after in zip(one, one[1:], strict=False):
        assert after["start"] == pytest.approx(before["end"])
    # Shared by characters: every card of the scene is up for the same time per character.
    rates = [(c["end"] - c["start"]) / len(" ".join(c["lines"])) for c in one]
    assert max(rates) == pytest.approx(min(rates), rel=0.01)


def test_a_long_sentence_becomes_many_short_cards_and_the_srt_reads_back():
    from app.media.assembler import (
        CAPTION_LINE_CHARS,
        CAPTION_MAX_WORDS,
        caption_cues,
        generate_subtitles_srt,
    )
    from app.media.qc import caption_problems, parse_srt

    sentence = (
        "The rover drilled through layered sandstone for eleven hours while the orbiter "
        "photographed the delta from above and the scientists on Earth waited for the first "
        "spectrometer reading to come home"
    )
    scenes = [
        {
            "scene_index": 1,
            "duration_seconds": 12.0,
            "audio_seconds": 11.5,
            "voiceover_segment": sentence,
        }
    ]
    cues = caption_cues(scenes)
    assert len(cues) >= len(sentence.split()) // CAPTION_MAX_WORDS
    for cue in cues:
        assert 2 <= len(" ".join(cue["lines"]).split()) <= CAPTION_MAX_WORDS
        assert all(0 < len(line) <= CAPTION_LINE_CHARS for line in cue["lines"])
    assert _words(" ".join(" ".join(c["lines"]) for c in cues)) == _words(sentence)
    assert cues[0]["start"] == 0.0 and cues[-1]["end"] == pytest.approx(11.5, abs=0.01)

    # The SRT the studio writes is the SRT quality control reads back, and passes.
    parsed = parse_srt(generate_subtitles_srt(scenes))
    assert [c["lines"] for c in parsed] == [c["lines"] for c in cues]
    assert parsed[-1]["end"] == pytest.approx(11.5, abs=0.001)
    assert caption_problems(parsed) == []

    # A scene with no words has no cue; nothing invents a caption from a visual prompt.
    assert (
        caption_cues([{"scene_index": 1, "duration_seconds": 3.0, "voiceover_segment": ""}]) == []
    )
    # One lone word at the end of a passage joins the card before it: never a one-word card
    # where a second word exists.
    lone = caption_cues(
        [
            {
                "scene_index": 1,
                "duration_seconds": 4.0,
                "audio_seconds": 3.0,
                "voiceover_segment": "One two three four five six.",
            }
        ]
    )
    assert [len(" ".join(c["lines"]).split()) for c in lone] in ([4, 2], [3, 3], [2, 4])


def test_caption_timing_follows_the_voices_word_alignment_when_the_take_has_it():
    """With the voice's own word timing (ElevenLabs' alignment, or an adapter's word_timings),
    each card comes up on its first word, not on a share of the characters."""
    from app.media.assembler import caption_cues

    text = "Nepal is paying for a crisis it did not create."
    starts = [0.12, 0.61, 0.80, 1.45, 1.70, 1.81, 2.60, 2.71, 2.95, 3.10]
    words = [
        {"word": word, "start": start, "end": start + 0.2}
        for word, start in zip(text.split(), starts, strict=True)
    ]
    planned = {
        "scene_index": 1,
        "duration_seconds": 4.0,
        "audio_seconds": 3.6,
        "voiceover_segment": text,
    }
    aligned = caption_cues(
        [
            {
                **planned,
                "voice_segments": [{"text": text, "offset": 0.0, "seconds": 3.6, "words": words}],
            },
            {
                "scene_index": 2,
                "duration_seconds": 3.0,
                "audio_seconds": 2.0,
                "voiceover_segment": "Yet it pays.",
                "voice_segments": [
                    {
                        "text": "Yet it pays.",
                        "offset": 0.0,
                        "seconds": 2.0,
                        "words": [
                            {"word": "Yet", "start": 0.3, "end": 0.5},
                            {"word": "it", "start": 0.55, "end": 0.7},
                            {"word": "pays.", "start": 0.9, "end": 1.4},
                        ],
                    }
                ],
            },
        ]
    )
    shared = caption_cues([planned])
    first_scene = [c for c in aligned if c["scene_index"] == 1]
    assert all(c["timing"] == "alignment" for c in aligned)
    position = 0
    for cue in first_scene:
        assert cue["start"] == pytest.approx(starts[position])
        position += len(" ".join(cue["lines"]).split())
    assert position == len(starts)
    # Scene two starts on its own clock (4.0) plus its first word (0.3).
    assert aligned[len(first_scene)]["start"] == pytest.approx(4.3)
    # The same words shared by characters land elsewhere: the alignment is what moved them.
    assert [c["start"] for c in first_scene] != pytest.approx([c["start"] for c in shared])
    assert all(c["timing"] == "character_share" for c in shared)

    # A timing that does not match the words said (another count) is not trusted.
    mismatched = caption_cues(
        [
            {
                **planned,
                "voice_segments": [
                    {"text": text, "offset": 0.0, "seconds": 3.6, "words": words[:4]}
                ],
            }
        ]
    )
    assert all(c["timing"] == "character_share" for c in mismatched)


def test_elevenlabs_character_alignment_is_read_as_words():
    from app.media.assembler import words_from_alignment

    text = "Nepal pays."
    alignment = {
        "characters": list(text),
        "character_start_times_seconds": [0.1 + 0.05 * i for i in range(len(text))],
        "character_end_times_seconds": [0.15 + 0.05 * i for i in range(len(text))],
    }
    assert words_from_alignment(alignment) == [
        {"word": "Nepal", "start": pytest.approx(0.1), "end": pytest.approx(0.35)},
        {"word": "pays.", "start": pytest.approx(0.4), "end": pytest.approx(0.65)},
    ]
    assert words_from_alignment(None) is None
    assert words_from_alignment({"characters": ["a"]}) is None
    assert (
        words_from_alignment({"characters": ["a", "b"], "character_start_times_seconds": [0.0]})
        is None
    )


def test_a_scene_lasts_its_words_and_its_full_breath_and_a_silent_card_one_beat():
    """2026-10-01 (DISK_AND_BREATHS, after QC_SPANS): quality control now counts the breath the
    timeline plans after each scene's words, so the timeline no longer shrinks the breaths to
    keep the film within 0.9 s of its narration (six scenes kept about 0.11 s each and every
    cut felt rushed). A silent composed scene lasts at most what QC allows its kind
    (qc.MAX_SILENT_CARD_SECONDS); a writer's longer plan is cut to it, not failed."""
    from app.media import assembler
    from app.media.assembler import SPOKEN_TAIL_SECONDS, TIMELINE_FPS, scene_spans
    from app.media.qc import MAX_SILENT_CARD_SECONDS

    # 0.12 s since 2026-10-02, after each take's own silence is trimmed (audit Q4).
    assert SPOKEN_TAIL_SECONDS == 0.12
    assert not hasattr(assembler, "FILM_OVER_NARRATION_SECONDS")

    def whole_frames(spans: list[float]) -> bool:
        return all(abs(s * TIMELINE_FPS - round(s * TIMELINE_FPS)) < 1e-6 for s in spans)

    def up(seconds: float) -> float:
        return math.ceil(seconds * TIMELINE_FPS - 1e-6) / TIMELINE_FPS

    # Two scenes: the full breath after each, never past the plan, on whole frames.
    two = scene_spans([5.0, 5.0], [4.0, 4.6])
    assert two == pytest.approx([99 / 24, 114 / 24])
    assert whole_frames(two)
    # Words longer than the plan are never cut: the scene lasts its words.
    assert scene_spans([4.0], [5.2]) == pytest.approx([125 / 24])
    # A breath never runs past the plan: 4.9 s of words under a 5 s plan keep 0.1 s.
    assert scene_spans([5.0], [4.9]) == pytest.approx([up(5.0)])
    # A scene with no words keeps its planned length.
    assert scene_spans([3.0], [0.0]) == pytest.approx([3.0])
    # Six scenes with a second of slack each: every one keeps its full breath.
    planned, spoken = [5.0] * 6, [4.0, 3.2, 4.4, 3.9, 4.1, 2.8]
    six = scene_spans(planned, spoken)
    assert whole_frames(six)
    assert six == pytest.approx([up(s + SPOKEN_TAIL_SECONDS) for s in spoken])
    assert sum(six) - sum(spoken) >= 6 * SPOKEN_TAIL_SECONDS - 1e-9
    assert sum(six) - sum(spoken) <= 6 * SPOKEN_TAIL_SECONDS + 6 / TIMELINE_FPS

    # Silent composed scenes: one beat each, never longer than QC allows their kind.
    kinds = ["LIVE", "BLACK", "DATA_CARD", "TITLE_CARD", "BLACK", "LIVE"]
    spans = scene_spans(
        [5.0, 3.0, 6.0, 4.0, 1.5, 4.0], [4.0, 0.0, 0.0, 0.0, None, 0.0], kinds=kinds
    )
    assert spans == pytest.approx(
        [
            up(4.0 + SPOKEN_TAIL_SECONDS),
            MAX_SILENT_CARD_SECONDS["BLACK"],
            MAX_SILENT_CARD_SECONDS["DATA_CARD"],
            MAX_SILENT_CARD_SECONDS["TITLE_CARD"],
            1.5,  # a plan under the maximum stands
            4.0,  # a silent LIVE scene is not a card: its plan stands (QC counts it)
        ]
    )
    assert whole_frames(spans)
    # A card with words is narration: its words and a breath, like any scene.
    assert scene_spans([6.0], [2.0], kinds=["DATA_CARD"]) == pytest.approx([up(2.12)])


class AlignedVoice:
    """A narrator that returns real WAV audio, with ElevenLabs-shaped character alignment
    when ``aligned`` (the /with-timestamps answer), and none otherwise."""

    PROVIDER_NAME = "TEST_ALIGNED_VOICE"
    model = "test-voice"
    voice_id = "voice-1"
    integration_id = "conn-voice"

    def __init__(self, aligned: bool):
        self.aligned = aligned
        self.starts: dict[str, list[float]] = {}

    async def synthesize(self, text, **_kwargs):
        import io
        import math
        import wave

        from app.providers.media_base import TTSResult

        words = text.split()
        # Uneven pacing, so word timing and a share of the characters cannot agree.
        starts, clock = [], 0.15
        for position, word in enumerate(words):
            starts.append(round(clock, 3))
            clock += 0.18 + 0.05 * len(word) + (0.35 if position == 1 else 0.0)
        seconds = round(clock + 0.2, 3)
        self.starts[text] = starts
        rate = 48000
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(
                b"".join(
                    int(9000 * math.sin(2 * math.pi * 220 * n / rate)).to_bytes(
                        2, "little", signed=True
                    )
                    for n in range(int(seconds * rate))
                )
            )
        raw: dict = {"provider": self.PROVIDER_NAME}
        if self.aligned:
            characters, begin, end = [], [], []
            for position, word in enumerate(words):
                if position:
                    characters.append(" ")
                    begin.append(starts[position] - 0.01)
                    end.append(starts[position])
                for offset, char in enumerate(word):
                    characters.append(char)
                    begin.append(starts[position] + 0.04 * offset)
                    end.append(starts[position] + 0.04 * (offset + 1))
            raw["alignment"] = {
                "characters": characters,
                "character_start_times_seconds": begin,
                "character_end_times_seconds": end,
            }
        return TTSResult(
            audio_bytes=buffer.getvalue(),
            format="wav",
            duration_seconds=seconds,
            sample_rate=rate,
            raw_response=raw,
        )


requires_libass = pytest.mark.skipif(
    not has_filter(find_ffmpeg(), "subtitles"),
    reason="the local ffmpeg has no libass (subtitles filter): burnt captions cannot be measured",
)


def _caption_pixels(film: Path, times: list[float], threshold: int = 60) -> list[set]:
    """The bright pixels of the film's frames at ``times`` (the stills are black, so every
    bright pixel is caption), as (x, y) sets, one per sampled frame."""
    import subprocess

    found = []
    for moment in times:
        raw = subprocess.run(  # noqa: S603
            [
                find_ffmpeg(),
                "-nostdin",
                "-v",
                "error",
                "-ss",
                f"{moment:.3f}",
                "-i",
                str(film),
                "-frames:v",
                "1",
                "-vf",
                "format=gray",
                "-f",
                "rawvideo",
                "-",
            ],
            capture_output=True,
            check=True,
        ).stdout
        width = 1080
        found.append(
            {
                (index % width, index // width)
                for index in range(0, len(raw), 1)
                if raw[index] > threshold
            }
        )
    return found


@requires_libass
def test_a_real_film_is_24_fps_within_a_second_of_its_words_with_captions_in_the_safe_area(
    engine, tmp_path: Path
):
    from app.media import cards
    from app.media.assembler import TIMELINE_FPS
    from app.media.qc import parse_srt, probe_media_file
    from test_motion import StubImages

    sb_id, _ = _seeded_storyboard(engine, tmp_path)
    voice = AlignedVoice(aligned=True)
    render = assemble_video_job(
        engine,
        sb_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=StubImages(),
        tts_adapter=voice,
        # A TEST film: no motion model here, and PRODUCTION refuses a still the Owner did
        # not choose (the fallback gate); the timeline and the captions are what is read.
        environment="TEST",
    )
    production = render["production"]
    film = Path(render["file_path"])

    # The timeline: 24 fps, recorded for quality control, and the file says the same.
    assert production["timeline"]["fps"] == TIMELINE_FPS == 24
    probe = probe_media_file(film)
    assert probe["video_fps"] == pytest.approx(24.0)
    # Within a second of the narration: the planned six seconds are not padded with silence.
    narration = sum(scene["audio_seconds"] for scene in production["scenes"])
    breaths = 2 * production["timeline"]["spoken_tail_seconds"]
    assert breaths == pytest.approx(0.24)
    assert probe["duration_seconds"] <= narration + breaths + 1.0, (
        probe["duration_seconds"],
        narration,
    )
    # Each scene keeps its words and its full breath, rounded up to a frame at most.
    assert render["duration_seconds"] <= narration + breaths + 2 / TIMELINE_FPS + 1e-6
    spans = production["timeline"]["spans"]
    assert [s["scene_index"] for s in spans] == [1, 2]
    # What quality control reads of each span: its kind and how long its words are.
    for span, scene in zip(spans, production["scenes"], strict=True):
        assert span["kind"] == "LIVE"
        assert span["spoken_seconds"] == pytest.approx(scene["audio_seconds"])
    assert spans[1]["start"] == pytest.approx(spans[0]["end"])

    # Captions: ASS, Inter Bold from the studio's own verified file, burnt in.
    captions = production["captions"]
    assert captions["burned_in"] is True
    ass = Path(captions["ass"])
    assert ass.is_file() and ass.parent == film.parent
    script = ass.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in script and "PlayResY: 1920" in script
    style = next(line for line in script.splitlines() if line.startswith("Style:")).split(",")
    assert style[1] == cards.font_family(cards.BOLD)
    assert 72 <= float(style[2]) <= 80  # 74 since audit Q7 (2026-10-02)
    assert 3 <= float(style[16]) <= 4  # outline
    font_copy = film.parent / "fonts" / cards.BOLD
    assert font_copy.read_bytes() == cards.font_path(cards.BOLD).read_bytes()
    with Session(engine) as session:
        args = " ".join(session.get(VideoRenderJob, render["job_id"]).command_args_json)
    assert "subtitles=filename=captions.ass:fontsdir=fonts" in args

    # The voice's own word timing placed the cards: each comes up on its first word.
    assert captions["timing"] == {"alignment": 2, "character_share": 0}
    cues = parse_srt(Path(captions["srt"]).read_text(encoding="utf-8"))
    scene_one = [c for c in cues if c["start"] < spans[0]["end"] - 1e-3]
    said = "Fixture narration segment 1."
    word_starts = voice.starts[said]
    position = 0
    for cue in scene_one:
        assert cue["start"] == pytest.approx(word_starts[position], abs=0.002)
        position += len(" ".join(cue["lines"]).split())
    assert position == len(said.split())

    # No caption pixel outside the safe area, on frames sampled in the middle of every cue.
    frames = _caption_pixels(film, [(c["start"] + c["end"]) / 2 for c in cues])
    assert all(frames), "a caption is on every sampled frame"
    for pixels in frames:
        xs = [x for x, _ in pixels]
        ys = [y for _, y in pixels]
        assert min(xs) >= cards.SAFE_RECT[0] and max(xs) <= 1080 - 120, (min(xs), max(xs))
        assert min(ys) >= cards.SAFE_RECT[1] and max(ys) <= 1500, (min(ys), max(ys))

    # Without the voice's timing the same film is timed by the characters, and says so.
    sb_two, _ = _seeded_storyboard(engine, tmp_path)
    plain = assemble_video_job(
        engine,
        sb_two,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=StubImages(),
        tts_adapter=AlignedVoice(aligned=False),
        environment="TEST",
    )
    assert plain["production"]["captions"]["timing"] == {"alignment": 0, "character_share": 2}


@requires_libass
def test_the_widest_caption_cards_stay_inside_the_safe_area(tmp_path: Path):
    """The worst case drawn on black: long Romanian words in capitals, five to a card. Every
    lit pixel stays inside SAFE_RECT, at or above y 1500 and clear of the right 120 px."""
    import subprocess

    from app.media import cards
    from app.media.assembler import (
        ass_captions_filter,
        ass_from_cues,
        caption_cues,
        install_caption_fonts,
    )

    text = (
        "RESPONSABILITĂȚILE EXTRAORDINARE ÎNTOTDEAUNA NEÎNDOIELNIC INTERGUVERNAMENTALE. "
        "Țara plătește o factură pe care nu a făcut-o niciodată, iar lumea privește."
    )
    cues = caption_cues(
        [
            {
                "scene_index": 1,
                "duration_seconds": 8.0,
                "audio_seconds": 8.0,
                "voiceover_segment": text,
            }
        ]
    )
    (tmp_path / "captions.ass").write_text(ass_from_cues(cues), encoding="utf-8")
    install_caption_fonts(tmp_path)
    moments = [(c["start"] + c["end"]) / 2 for c in cues]
    picks = "+".join(f"eq(n\\,{int(m * 24)})" for m in moments)
    raw = subprocess.run(  # noqa: S603
        [
            find_ffmpeg(),
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:size=1080x1920:rate=24:duration=8",
            "-vf",
            f"{ass_captions_filter('captions.ass')},select='{picks}',format=gray",
            "-fps_mode",
            "passthrough",
            "-f",
            "rawvideo",
            "-",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    ).stdout
    size = 1080 * 1920
    assert len(raw) == size * len(moments)
    for frame in range(len(moments)):
        lit = [index for index in range(frame * size, (frame + 1) * size) if raw[index] > 30]
        assert lit, f"card {frame + 1} drew nothing"
        xs = [(index - frame * size) % 1080 for index in lit]
        ys = [(index - frame * size) // 1080 for index in lit]
        assert min(xs) >= cards.SAFE_RECT[0] and max(xs) <= 960, (frame, min(xs), max(xs))
        assert min(ys) >= cards.SAFE_RECT[1] and max(ys) <= 1500, (frame, min(ys), max(ys))


def test_srt_parsing_refuses_what_is_not_srt_and_reads_what_is():
    from app.media.qc import caption_problems, parse_srt

    text = (
        "1\n00:00:00,000 --> 00:00:02,500\nA first cue\nwith two lines\n\n"
        "2\n00:00:02,500 --> 00:00:04,000\nSecond.\n"
    )
    cues = parse_srt(text)
    assert [c["index"] for c in cues] == [1, 2]
    assert cues[0]["start"] == 0.0 and cues[0]["end"] == 2.5
    assert cues[0]["lines"] == ["A first cue", "with two lines"]
    assert caption_problems(cues) == []

    with pytest.raises(ValueError):
        parse_srt("1\n00:00:00,000 -> 00:00:02,500\nno arrow\n")
    with pytest.raises(ValueError):
        parse_srt("1\n00:00:03,000 --> 00:00:02,500\nends before it starts\n")
    assert parse_srt("") == []

    # Rules a cue must keep to stay readable on a phone: two lines, forty-two characters.
    too_long = parse_srt("1\n00:00:00,000 --> 00:00:02,000\n" + "x" * 43 + "\n")
    assert any("42" in p for p in caption_problems(too_long))
    three = parse_srt("1\n00:00:00,000 --> 00:00:02,000\na\nb\nc\n")
    assert any("2 lines" in p for p in caption_problems(three))
    overlap = parse_srt(
        "1\n00:00:00,000 --> 00:00:03,000\na\n\n2\n00:00:02,000 --> 00:00:04,000\nb\n"
    )
    assert any("overlap" in p for p in caption_problems(overlap))


@requires_ffmpeg
def test_the_film_carries_burnt_captions_and_normalised_loudness(engine, tmp_path: Path):
    from types import SimpleNamespace

    from app.media.qc import probe_media_file
    from app.media.toolchain import LOUDNESS_BAND_LUFS, TRUE_PEAK_CEILING_DBTP, measure_loudness

    sb_id, _ = _seeded_storyboard(engine, tmp_path)
    corr_id = str(uuid4())
    render = assemble_video_job(engine, sb_id, corr_id, storage_root=tmp_path / "media")
    production = render["production"]

    # Loudness: the mixed narration was normalised to the platform norm, both readings kept.
    loudness = production["audio"]["loudness"]
    assert loudness["target_lufs"] == -14.0
    assert loudness["passes"] in (1, 2)
    assert "integrated_lufs" in loudness["input"]
    low, high = LOUDNESS_BAND_LUFS
    assert low <= loudness["output"]["integrated_lufs"] <= high, loudness
    assert loudness["output"]["true_peak_dbtp"] <= TRUE_PEAK_CEILING_DBTP

    # And the film itself measures inside the band, after the AAC encode.
    film = Path(render["file_path"])
    measured = measure_loudness(find_ffmpeg(), film)
    assert measured is not None and low <= measured["integrated_lufs"] <= high, measured
    assert measured["true_peak_dbtp"] <= TRUE_PEAK_CEILING_DBTP

    # Captions: cues from the narration, burnt in, and the SRT kept beside the film.
    captions = production["captions"]
    assert captions["burned_in"] is True
    assert captions["cues"] >= 2
    srt = film.parent / "captions.srt"
    assert srt.is_file() and captions["srt"] == str(srt)
    with Session(engine) as session:
        job = session.get(VideoRenderJob, render["job_id"])
        args = " ".join(job.command_args_json)
    # Burnt from the ASS script beside the film, in the studio's own Inter Bold.
    assert "subtitles=filename=captions.ass:fontsdir=fonts" in args
    script = (film.parent / "captions.ass").read_text(encoding="utf-8")
    assert "BorderStyle" in script and "&H00FFFFFF" in script
    # A burnt-in film still plays: the video stream is there and 9:16.
    probe = probe_media_file(film)
    assert probe["ok"] and (probe["width"], probe["height"]) == (1080, 1920)

    # Quality control reads the same film: audio in band, captions cover the narration.
    qc = evaluate_media_qc(engine, render["output_asset_id"], corr_id)
    audio = qc["checks_json"]["audio_qc"]
    assert audio["passed"] is True, audio
    assert low <= audio["integrated_lufs"] <= high
    caps = qc["checks_json"]["captions_qc"]
    assert caps["passed"] is True, caps
    assert caps["cues"] == captions["cues"] and caps["covers_narration"] is True
    assert caps["burned_in"] is True
    # The placeholder visuals still block publication; nothing here weakens that.
    assert qc["checks_json"]["content_source_qc"]["passed"] is False

    # The Owner may keep the picture clean: the SRT stays beside the film, nothing is burnt.
    sb_two, _ = _seeded_storyboard(engine, tmp_path)
    clean = assemble_video_job(
        engine,
        sb_two,
        str(uuid4()),
        storage_root=tmp_path / "media",
        settings=SimpleNamespace(captions_burn_in=False),
    )
    assert clean["production"]["captions"]["burned_in"] is False
    assert (Path(clean["file_path"]).parent / "captions.srt").is_file()
    with Session(engine) as session:
        job = session.get(VideoRenderJob, clean["job_id"])
        assert "subtitles=" not in " ".join(job.command_args_json)


def _render_with_motion_record(engine, tmp_path: Path, refused: int, made: int) -> str:
    """A COMPLETED render whose manifest says how many scenes moved and how many fell back.

    The file is not on disk: quality control's technical checks fail on it, which is fine,
    because what is asserted here is the motion gate alone.
    """
    from app.media.models import MediaAsset, VideoRenderJob

    sb_id, _ = _seeded_storyboard(engine, tmp_path)
    asset_id, job_id = str(uuid4()), str(uuid4())
    scenes = []
    for index in range(1, refused + made + 1):
        motion = {"provider": "TEST", "model": "m", "integration_id": "c"}
        if index <= refused:
            motion["refused"] = "the model refused this shot"
        else:
            motion["bytes"] = 1024
        scenes.append({"scene_index": index, "motion": motion})
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=str(tmp_path / "missing.mp4"),
                file_size_bytes=1,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=12.0,
                provider_name="TEST_IMAGE_PROVIDER",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="0" * 64,
                created_at=utc_now(),
            )
        )
        session.add(
            VideoRenderJob(
                id=job_id,
                storyboard_id=sb_id,
                output_asset_id=asset_id,
                status="COMPLETED",
                started_at=utc_now(),
                production_json={
                    "scenes": scenes,
                    "motion": {
                        "scenes": refused + made,
                        "clips": made,
                        "motion_scenes": made,
                        "fallback_scenes": refused,
                    },
                },
            )
        )
    return asset_id


def test_too_many_fallback_scenes_fail_a_production_film_and_warn_a_test_one(engine, tmp_path):
    from types import SimpleNamespace

    # Three of four scenes fell back to a push: more than half. In PRODUCTION that is a
    # slideshow sold as a film, and the gate says so.
    asset = _render_with_motion_record(engine, tmp_path, refused=3, made=1)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"
    qc = evaluate_media_qc(engine, asset, str(uuid4()))
    motion = qc["checks_json"]["motion_qc"]
    assert motion["passed"] is False
    assert (motion["motion_scenes"], motion["fallback_scenes"]) == (1, 3)
    # CLIP_QC (2026-10-01): in PRODUCTION no LIVE scene may be a still unless the Owner
    # chose it for that scene; the old default of half the scenes is gone.
    assert motion["max_fallback_scenes"] == 0
    assert motion["unchosen"] == [1, 2, 3]
    assert motion["environment"] == "PRODUCTION"
    assert any("fallback" in r.lower() or "push" in r.lower() for r in qc["failure_reasons_json"])

    # The same film in TEST: two motion scenes are policy, the rest push; a warning, no fail.
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "TEST"
    qc = evaluate_media_qc(engine, asset, str(uuid4()))
    motion = qc["checks_json"]["motion_qc"]
    assert motion["passed"] is True and motion["warning"]
    assert not any("fallback" in r.lower() for r in qc["failure_reasons_json"])

    # One refusal fails production whatever the setting says: a setting cannot loosen it.
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"
    strict = _render_with_motion_record(engine, tmp_path, refused=1, made=3)
    qc = evaluate_media_qc(
        engine, strict, str(uuid4()), settings=SimpleNamespace(max_fallback_scenes=0)
    )
    assert qc["checks_json"]["motion_qc"]["passed"] is False
    qc = evaluate_media_qc(
        engine, strict, str(uuid4()), settings=SimpleNamespace(max_fallback_scenes=3)
    )
    assert qc["checks_json"]["motion_qc"]["passed"] is False


@requires_ffmpeg
def test_the_render_counts_its_own_fallbacks(engine, tmp_path):
    """The manifest carries the count the gate reads: scenes that moved, scenes that fell back."""
    from test_motion import StubImages, StubMotion, a_clip

    sb_id, _ = _seeded_storyboard(engine, tmp_path)
    motion = StubMotion(a_clip(tmp_path), refuse={1})
    render = assemble_video_job(
        engine,
        sb_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=StubImages(),
        video_adapter_for_scene=lambda scene: motion,
        # A TEST film: in PRODUCTION the refused scene would be a still the Owner never chose.
        environment="TEST",
    )
    summary = render["production"]["motion"]
    assert summary["motion_scenes"] == 1 and summary["fallback_scenes"] == 1
    assert summary["scenes"] == 2 and summary["clips"] == 1


# ------------------------------------------------------ the Owner's own render button
# Measured before this work: the daily run handed `settings=` (captions_burn_in, the
# fallback ceiling) to the assembler and to quality control, and the media route called both
# without it, so the Owner's render button made a film under different rules than the day.


def test_the_owners_render_button_hands_the_settings_to_the_camera_and_to_qc(
    client, headers, engine, settings, tmp_path: Path, monkeypatch
):
    from app.factual.models import StoryReview
    from app.media.models import Storyboard

    storyboard_id, _ = _seeded_storyboard(engine, tmp_path)
    with Session(engine) as session, session.begin():
        board = session.get(Storyboard, storyboard_id)
        session.add(
            StoryReview(
                id=str(uuid4()),
                script_id=board.script_draft_id,
                verdict="PASS",
                checks_json={},
                retention_json={},
                scores_json={},
                notes_json={},
                estimated_seconds=12.0,
                created_at=utc_now(),
            )
        )
    received: dict[str, dict] = {}
    asset_id = str(uuid4())

    def fake_assemble(engine_, storyboard, correlation, **kwargs):
        received["render"] = kwargs
        return {"job_id": str(uuid4()), "output_asset_id": asset_id, "provenance_hash": "0"}

    def fake_qc(engine_, asset, correlation, **kwargs):
        received["qc"] = kwargs
        return {
            "id": str(uuid4()),
            "media_asset_id": asset,
            "status": "PASSED",
            "score": 1.0,
            "checks_json": {},
            "failure_reasons_json": [],
            "verified_at": utc_now(),
        }

    monkeypatch.setattr("app.media.router.assemble_video_job", fake_assemble)
    monkeypatch.setattr("app.media.router.evaluate_media_qc", fake_qc)

    response = client.post(f"/api/v1/media/render/{storyboard_id}", headers=headers)
    assert response.status_code == 200, response.text
    assert received["render"]["settings"] is settings
    assert received["qc"]["settings"] is settings

    # Quality control asked for on its own reads the same settings.
    received.clear()
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=str(tmp_path / "final_short_9_16.mp4"),
                file_size_bytes=1,
                mime_type="video/mp4",
                provider_name="STUDIO_INTERNAL",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="0" * 64,
                created_at=utc_now(),
            )
        )
    response = client.post(f"/api/v1/media/qc/{asset_id}", headers=headers)
    assert response.status_code == 200, response.text
    assert received["qc"]["settings"] is settings


# --------------------------------------------------------------------------------------------
# A render the vendor stopped: the job keeps what was attempted, never what was planned
# --------------------------------------------------------------------------------------------


def test_a_render_refused_at_the_third_scene_keeps_the_two_it_made_and_the_books_charge_for_them(
    engine, tmp_path: Path
):
    """`_fail_job` used to leave `production_json` untouched, so a render the vendor stopped
    looked free: the Accountant found no scenes and charged nothing although the shots were
    generated and billed. The job now carries the scenes it actually made — and only those.

    Three scenes are planned and the vendor refuses the third, so the plan and the attempt
    differ by exactly one scene: a job that wrote the plan instead would charge the day for
    a shot that was never asked for, which is the opposite error and just as wrong.
    """
    from app.economy.accountant import record_failed_render_cost
    from app.economy.models import ProviderCostRecord
    from app.economy.prices import PriceCommand, set_price
    from app.integrations.services import SaveIntegration, save
    from app.integrations.vault import CredentialVault
    from app.providers.media_http import MediaProviderError

    connection = str(uuid4())
    save(
        engine,
        CredentialVault(tmp_path / "render.credentials.key"),
        connection,
        SaveIntegration(
            kind="elevenlabs", name="Voice", config={}, secrets={"api_key": "k-" + connection}
        ),
    )
    set_price(
        engine,
        PriceCommand(
            command_id=uuid4(),
            provider_kind="elevenlabs",
            resource="*",
            unit="per_1k_characters",
            usd="0.30",
        ),
    )
    storyboard_id, _claim_id = _seeded_storyboard(engine, tmp_path, scenes=3)

    class VoiceThatStopsAtTheThirdScene(DeterministicTTSAdapter):
        PROVIDER_NAME = "elevenlabs"
        model = "eleven_turbo_v2_5"
        integration_id = connection
        calls = 0

        async def synthesize(self, text: str, **kwargs):
            type(self).calls += 1
            if type(self).calls > 2:
                raise MediaProviderError("the vendor refused this narration")
            return await super().synthesize(text, **kwargs)

    with pytest.raises(MediaProviderError):
        assemble_video_job(
            engine,
            storyboard_id,
            str(uuid4()),
            storage_root=tmp_path / "media",
            tts_adapter=VoiceThatStopsAtTheThirdScene(),
        )

    with Session(engine) as session:
        job = session.scalars(select(VideoRenderJob)).one()
        job_id = job.id
        production = job.production_json if isinstance(job.production_json, dict) else {}
    assert job.status == "FAILED", "a refused render left its job open"
    attempted = list(production.get("scenes") or [])
    assert [scene["scene_index"] for scene in attempted] == [1, 2], attempted
    assert all(scene["characters"] > 0 and scene["model_id"] for scene in attempted)

    charged = record_failed_render_cost(engine, job_id, correlation_id=str(uuid4()))

    assert (charged["scenes"], charged["recorded"], charged["unpriced_scenes"]) == (2, 2, 0)
    with Session(engine) as session:
        rows = sorted(
            session.scalars(select(ProviderCostRecord)), key=lambda r: r.external_reference
        )
    assert len(rows) == 2, "one row a scene, for the two scenes that were made"
    assert all(row.status == "ESTIMATED" and row.failed for row in rows)
    assert [row.external_reference for row in rows] == [
        f"render:{job_id}:failed:scene:1:voice",
        f"render:{job_id}:failed:scene:2:voice",
    ]
    # The same reading again charges nothing: a re-run of the books is not a second bill.
    assert record_failed_render_cost(engine, job_id)["recorded"] == 0


def test_the_picture_check_stands_down_when_there_is_nothing_to_look_at(engine, tmp_path):
    """Quality control has its own eye on the pictures now, and it certifies only what it
    saw. With no film on disk there is no frame to cut, and with an empty registry there is
    no model to cut it for: both report NOT_APPLICABLE with the reason, `passed` is None,
    and the report's verdict and failure reasons are exactly what they were before the check
    existed. Nothing here may start passing by absence."""
    from app.providers.registry import ProviderRegistry

    asset = _render_with_motion_record(engine, tmp_path, refused=1, made=3)
    without = evaluate_media_qc(engine, asset, str(uuid4()))
    with_empty_registry = evaluate_media_qc(
        engine, asset, str(uuid4()), registry=ProviderRegistry()
    )

    for report in (without, with_empty_registry):
        picture = report["checks_json"]["picture_qc"]
        assert picture["status"] == "NOT_APPLICABLE" and picture["passed"] is None
        assert picture["detail"] and picture["model_used"] is False
        drift = report["checks_json"]["character_drift_qc"]
        assert drift["passed"] is None and drift["status"] in ("NOT_IMPLEMENTED", "NOT_APPLICABLE")
    assert without["status"] == with_empty_registry["status"]
    assert without["failure_reasons_json"] == with_empty_registry["failure_reasons_json"]


# ------------------------------------------------ the Owner's own render sees what the day sees
# Measured before this work: the media stage passed the plan's `image_chain` and
# `reference_for_scene` to the camera and the registry and the encoder to quality control,
# and this route passed none of the four. So the Owner's button drew every scene with one
# vendor and no character's reference, and his quality control reported the picture and
# character checks NOT_APPLICABLE while the day measured them on the same film.


def _approved_storyboard(engine, tmp_path: Path) -> str:
    """A storyboard whose story has been read and passed, ready for the render route."""
    from app.factual.models import StoryReview
    from app.media.models import Storyboard

    storyboard_id, _ = _seeded_storyboard(engine, tmp_path)
    with Session(engine) as session, session.begin():
        board = session.get(Storyboard, storyboard_id)
        session.add(
            StoryReview(
                id=str(uuid4()),
                script_id=board.script_draft_id,
                verdict="PASS",
                checks_json={},
                retention_json={},
                scores_json={},
                notes_json={},
                estimated_seconds=12.0,
                created_at=utc_now(),
            )
        )
    return storyboard_id


def _planner(chain, reference_for_scene):
    """`render_plan`, faked at the route's import boundary: the plan is what the route reads."""

    def fake_render_plan(engine_, vault, board_id):
        return {
            "plan": {"purposes": {}, "scenes": []},
            "tts_for_scene": lambda scene: None,
            "video_for_scene": lambda scene: None,
            "image": None,
            "image_chain": chain,
            "reference_for_scene": reference_for_scene,
        }

    return fake_render_plan


def _recording_assembler(received: dict, asset_id: str):
    def fake_assemble(engine_, storyboard, correlation, **kwargs):
        received["render"] = kwargs
        return {"job_id": str(uuid4()), "output_asset_id": asset_id, "provenance_hash": "0"}

    return fake_assemble


def _recording_qc(received: dict):
    def fake_qc(engine_, asset, correlation, **kwargs):
        received["qc"] = kwargs
        return {
            "id": str(uuid4()),
            "media_asset_id": asset,
            "status": "PASSED",
            "score": 1.0,
            "checks_json": {},
            "failure_reasons_json": [],
            "verified_at": utc_now(),
        }

    return fake_qc


def test_the_owners_render_draws_through_the_chain_and_his_qc_looks_at_the_pictures(
    client, headers, engine, settings, tmp_path: Path, monkeypatch
):
    """The four arguments the day passes and this route did not, at both of its call sites."""
    storyboard_id = _approved_storyboard(engine, tmp_path)
    received: dict[str, dict] = {}
    asset_id = str(uuid4())
    chain: list = [object()]

    def reference_for_scene(scene):
        return None

    monkeypatch.setattr("app.media.router.render_plan", _planner(chain, reference_for_scene))
    monkeypatch.setattr(
        "app.media.router.assemble_video_job", _recording_assembler(received, asset_id)
    )
    monkeypatch.setattr("app.media.router.evaluate_media_qc", _recording_qc(received))

    response = client.post(f"/api/v1/media/render/{storyboard_id}", headers=headers)

    assert response.status_code == 200, response.text
    assert received["render"]["image_chain"] is chain
    assert received["render"]["reference_for_scene"] is reference_for_scene
    assert received["qc"]["registry"] is client.app.app.state.registry
    assert received["qc"]["ffmpeg_path"] == settings.ffmpeg_path

    # And quality control asked for on its own: the same two, so the Owner's own reading of
    # a film measures what the day's reading of the same film measured.
    received.clear()
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=str(tmp_path / "final_short_9_16.mp4"),
                file_size_bytes=1,
                mime_type="video/mp4",
                provider_name="STUDIO_INTERNAL",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="0" * 64,
                created_at=utc_now(),
            )
        )
    response = client.post(f"/api/v1/media/qc/{asset_id}", headers=headers)

    assert response.status_code == 200, response.text
    assert received["qc"]["registry"] is client.app.app.state.registry
    assert received["qc"]["ffmpeg_path"] == settings.ffmpeg_path


def test_an_injected_image_adapter_is_still_the_only_vendor_the_render_uses(
    client, headers, engine, tmp_path: Path, monkeypatch
):
    """A test-injected adapter on app.state means *this* vendor draws the film. Handing the
    plan's chain as well would put the studio's own vendors in front of it, so the chain is
    passed only when nothing was injected — the same rule the route already applies to the
    injected voice."""
    storyboard_id = _approved_storyboard(engine, tmp_path)
    received: dict[str, dict] = {}
    injected = DeterministicVisualAdapter()
    client.app.app.state.image_adapter = injected
    monkeypatch.setattr("app.media.router.render_plan", _planner([object()], lambda scene: None))
    monkeypatch.setattr(
        "app.media.router.assemble_video_job", _recording_assembler(received, str(uuid4()))
    )
    monkeypatch.setattr("app.media.router.evaluate_media_qc", _recording_qc(received))

    response = client.post(f"/api/v1/media/render/{storyboard_id}", headers=headers)

    assert response.status_code == 200, response.text
    assert received["render"]["image_adapter"] is injected
    assert received["render"]["image_chain"] is None


def test_the_owners_render_refuses_to_invent_the_face_of_a_locked_character(
    client, headers, engine, tmp_path: Path, monkeypatch
):
    """`ReferenceRequired` is a ValueError, and this route answered every ValueError with 404
    — "storyboard not found" for a storyboard that exists. It is the studio declining to
    draw a locked look it has no sheet for, so it is 422 and it names the character."""
    from app.media.services import ReferenceRequired

    storyboard_id = _approved_storyboard(engine, tmp_path)
    monkeypatch.setattr("app.media.router.render_plan", _planner(None, lambda scene: None))

    def refusing_assemble(engine_, storyboard, correlation, **kwargs):
        raise ReferenceRequired("Sarah are înfățișarea blocată și nicio imagine de referință")

    monkeypatch.setattr("app.media.router.assemble_video_job", refusing_assemble)

    response = client.post(f"/api/v1/media/render/{storyboard_id}", headers=headers)

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "ReferenceRequired"
    assert "Sarah" in detail["detail"]


# ---------------------------------------------------------------------------
# The factual film records who is in it
# ---------------------------------------------------------------------------


def _factual_script(engine, scenes: list[dict], title: str = "Cast") -> str:
    """An APPROVED script with no unverified claim, ready to be storyboarded."""
    script_id, now = str(uuid4()), utc_now()
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        topic = TopicIdea(
            id=str(uuid4()),
            title=title,
            topic="test",
            angle="test",
            target_audience="general",
            novelty_score=0.8,
            status="SELECTED",
            created_at=now,
        )
        session.add(topic)
        session.flush()
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic.id,
                version=1,
                title=title,
                target_duration_seconds=30,
                voiceover_full_text=" ".join(str(s.get("narration") or "") for s in scenes),
                scenes_json=scenes,
                status="APPROVED",
                claim_ids_json=[],
                unverified_claim_ids_json=[],
                created_at=now,
            )
        )
    return script_id


def test_a_factual_scene_that_names_a_character_records_that_character(engine):
    """The studio's main product listed nobody, so the character check measured nothing.

    Measured before this: `generate_storyboard_from_script` wrote `character_ids_json=[]` on
    every scene of every factual film, and `character_drift_qc` answered "no scene in this
    film lists a character" on every one of them. A scene whose picture names Sarah
    Executive by her whole name now records her — and only her: the scene that shows the
    telescope shows nobody. The whole canonical name is the film's own statement of who is
    in it; the bare given name is the guess measured two tests below.
    """
    from app.media.services import storyboard_cast_note

    seed_default_character_bibles(engine)
    script_id = _factual_script(
        engine,
        [
            {
                "scene_index": 1,
                "visual_description": (
                    "Sarah Executive at the studio window, reading the day's figures"
                ),
                "narration": "The day starts with the numbers.",
            },
            {
                "scene_index": 2,
                "visual_description": "The telescope's golden mirror against the dark",
                "narration": "Sarah explains what the mirror does.",
            },
        ],
    )

    board = generate_storyboard_from_script(
        engine, script_id, "MOTION_GRAPHIC", "9:16", str(uuid4())
    )

    with Session(engine) as session:
        sarah = session.scalar(
            select(CharacterBible).where(CharacterBible.canonical_name == "Sarah Executive")
        )
        assert board["scenes"][0]["character_ids_json"] == [sarah.id]
        # Narration is the narrator's voice: a name spoken over a picture of a mirror does
        # not put that person in the shot.
        assert board["scenes"][1]["character_ids_json"] == []
        # The film has a cast, so there is no "by design" to explain.
        assert storyboard_cast_note(session, board["id"]) is None
    assert board["cast_note"] is None


def test_a_factual_film_of_landscapes_records_no_cast_and_says_it_is_by_design(engine):
    """An empty cast is recorded as a decision, not left as an omission.

    A check that finds no character can now tell "this film has no characters by design" from
    "nobody listed them": the storyboard's own creation event carries the note. Nothing is
    invented to give the character check something to measure.
    """
    from app.media.services import NO_CAST_BY_DESIGN, storyboard_cast_note

    seed_default_character_bibles(engine)
    script_id = _factual_script(
        engine,
        [
            {
                "scene_index": 1,
                "visual_description": "A spectrum with a water line marked",
                "narration": "A line of water.",
            },
            {
                "scene_index": 2,
                "visual_description": "The planet turning against its star",
                "narration": "A world that keeps it.",
            },
        ],
        title="Landscapes",
    )

    board = generate_storyboard_from_script(
        engine, script_id, "MOTION_GRAPHIC", "9:16", str(uuid4())
    )

    assert [scene["character_ids_json"] for scene in board["scenes"]] == [[], []]
    assert board["cast_note"] == NO_CAST_BY_DESIGN
    with Session(engine) as session:
        assert storyboard_cast_note(session, board["id"]) == NO_CAST_BY_DESIGN


def test_a_writers_own_cast_list_is_read_before_the_picture(engine):
    """The writer's cast for a scene is the strongest evidence of who is in it.

    The serial's script already carries `characters` per scene; a factual script that does
    the same is read the same way, by the first name the bible holds — "Aris", not
    "Dr. Aris Researcher", and not the title in front of it.
    """
    seed_default_character_bibles(engine)
    script_id = _factual_script(
        engine,
        [
            {
                "scene_index": 1,
                "visual_description": "Two chairs and a whiteboard of half-finished sums",
                "narration": "The research desk.",
                "characters": ["Aris"],
            }
        ],
        title="Writer's cast",
    )

    board = generate_storyboard_from_script(
        engine, script_id, "MOTION_GRAPHIC", "9:16", str(uuid4())
    )

    with Session(engine) as session:
        aris = session.scalar(
            select(CharacterBible).where(CharacterBible.canonical_name == "Dr. Aris Researcher")
        )
    assert board["scenes"][0]["character_ids_json"] == [aris.id]


def test_a_studio_with_no_character_bible_still_builds_a_storyboard(engine):
    """No bible, no cast, and no invention: the scenes are written exactly as before."""
    from app.media.services import NO_CAST_BY_DESIGN

    script_id = _factual_script(
        engine,
        [
            {
                "scene_index": 1,
                "visual_description": "Sarah at the studio window",
                "narration": "Nobody in this studio has a bible yet.",
            }
        ],
        title="No bible",
    )

    board = generate_storyboard_from_script(
        engine, script_id, "MOTION_GRAPHIC", "9:16", str(uuid4())
    )

    assert board["scenes"][0]["character_ids_json"] == []
    assert board["cast_note"] == NO_CAST_BY_DESIGN


def test_a_surname_the_bible_does_not_hold_is_not_the_studios_character(engine):
    """A telescope is not an employee: no cast is invented to give a gate something to do.

    "Vera Distribution Hub" is in the bible and "the Vera Rubin Observatory" is in half the
    astronomy scripts ever written. A given name followed by another capitalised word is
    somebody else's surname, so it is not counted; the whole canonical name always is.
    """
    from app.media.services import NO_CAST_BY_DESIGN

    seed_default_character_bibles(engine)
    script_id = _factual_script(
        engine,
        [
            {
                "scene_index": 1,
                "visual_description": "The Vera Rubin Observatory under a clear night sky",
                "narration": "A telescope that photographs the whole sky.",
            }
        ],
        title="Observatory",
    )

    board = generate_storyboard_from_script(
        engine, script_id, "MOTION_GRAPHIC", "9:16", str(uuid4())
    )

    assert board["scenes"][0]["character_ids_json"] == []
    assert board["cast_note"] == NO_CAST_BY_DESIGN


def test_a_name_the_prose_merely_spells_is_a_guess_and_casts_nobody(engine):
    """Three sentences measured on this tree, each of which used to cast an employee.

    "Hurricane Elena made landfall" recorded Elena Fact-Checker, "Lyra, the constellation,
    rises" recorded Lyra Voice Artist and "the Kael river delta" recorded Kael Video Editor,
    because a bare given name counted whenever the next word was lower case. What a cast is
    for decides this: a recorded character steers a paid render towards a portrait and
    refuses the film when the look is locked, so a name the studio merely guessed is not
    one. The scene stays empty, the guess is kept on the board's own record with the reading
    that produced it, and the note says the empty cast is a guess refused — not a film
    designed without people.
    """
    from app.media.services import NO_CAST_ONLY_GUESSED, storyboard_cast_record

    seed_default_character_bibles(engine)
    script_id = _factual_script(
        engine,
        [
            {
                "scene_index": 1,
                "visual_description": "Hurricane Elena made landfall before dawn",
                "narration": "The storm came ashore.",
            },
            {
                "scene_index": 2,
                "visual_description": "Lyra, the constellation, rises over the ridge",
                "narration": "A small harp of stars.",
            },
            {
                "scene_index": 3,
                "visual_description": "The Kael river delta seen from orbit",
                "narration": "Silt spreading into the sea.",
            },
        ],
        title="Three false positives",
    )

    board = generate_storyboard_from_script(
        engine, script_id, "MOTION_GRAPHIC", "9:16", str(uuid4())
    )

    assert [scene["character_ids_json"] for scene in board["scenes"]] == [[], [], []]
    with Session(engine) as session:
        names = {row.id: row.canonical_name for row in session.scalars(select(CharacterBible))}
        record = storyboard_cast_record(session, board["id"])
    guessed = {index: sorted(names[cid] for cid in ids) for index, ids in record["guessed"].items()}
    assert guessed == {
        "1": ["Elena Fact-Checker"],
        "2": ["Lyra Voice Artist"],
        "3": ["Kael Video Editor"],
    }
    assert record["note"] == NO_CAST_ONLY_GUESSED
    assert board["cast_note"] == NO_CAST_ONLY_GUESSED


def test_a_guess_is_not_recorded_twice_when_the_scene_states_the_same_person(engine):
    """A scene that states its cast is certain, and the guess for it is not kept beside it.

    The writer's own list is the film's statement of who is in the scene, whichever form of
    the name it writes; the prose of the same scene adds nothing to it.
    """
    from app.media.services import storyboard_cast_record

    seed_default_character_bibles(engine)
    script_id = _factual_script(
        engine,
        [
            {
                "scene_index": 1,
                "visual_description": "Sarah at the studio window, mid-sentence",
                "narration": "The day starts with the numbers.",
                "characters": ["Sarah"],
            }
        ],
        title="Stated and spelled",
    )

    board = generate_storyboard_from_script(
        engine, script_id, "MOTION_GRAPHIC", "9:16", str(uuid4())
    )

    with Session(engine) as session:
        sarah = session.scalar(
            select(CharacterBible).where(CharacterBible.canonical_name == "Sarah Executive")
        )
        record = storyboard_cast_record(session, board["id"])
    assert board["scenes"][0]["character_ids_json"] == [sarah.id]
    assert record["guessed"] == {}
    assert record["note"] is None


# --------------------------------------------------------------------------- the master
# Sound and encoding cost no credits to fix. The render masters the narration once (a WAV
# joined at 48 kHz, two-pass loudnorm at -2 dBTP, a limiter, one AAC encode) and copies that
# track into the film; a film already made can have its sound redone without touching one
# byte of its picture.


def _stream_hash(path: Path, selector: str) -> str:
    """The SHA-256 of every packet of one stream, as ffmpeg's streamhash muxer reads it."""
    import subprocess

    result = subprocess.run(  # noqa: S603
        [
            find_ffmpeg(),
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            selector,
            "-c",
            "copy",
            "-f",
            "streamhash",
            "-hash",
            "sha256",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=300,
    )
    return result.stdout.strip()


@requires_ffmpeg
def test_the_render_masters_the_narration_once_and_copies_it_into_the_film(engine, tmp_path):
    from app.media.qc import probe_media_file
    from app.media.toolchain import TRUE_PEAK_CEILING_DBTP, measure_loudness

    sb_id, _ = _seeded_storyboard(engine, tmp_path)
    render = assemble_video_job(engine, sb_id, str(uuid4()), storage_root=tmp_path / "media")
    loudness = render["production"]["audio"]["loudness"]
    assert loudness["applied"] is True
    assert loudness["true_peak_target_dbtp"] == -2.0
    assert loudness["true_peak_ceiling_dbtp"] == -1.0
    assert "alimiter=" in loudness["filter"] and "linear=true" in loudness["filter"]
    assert loudness["codec"] == "aac-lc 256k stereo 48 kHz"
    assert loudness["normalization_type"] in ("linear", "dynamic")
    # The output reading is taken from the delivered film, after the AAC encode.
    film = Path(render["file_path"])
    delivered = measure_loudness(find_ffmpeg(), film)
    assert loudness["output"]["true_peak_dbtp"] == pytest.approx(
        round(delivered["true_peak_dbtp"], 2), abs=0.01
    )
    assert delivered["true_peak_dbtp"] <= TRUE_PEAK_CEILING_DBTP

    with Session(engine) as session:
        job = session.get(VideoRenderJob, render["job_id"])
        args = list(job.command_args_json)
    # The film's own encode copies the mastered track: audio is AAC-encoded exactly once.
    assert args[args.index("-c:a") + 1] == "copy"
    assert "setrange=pc" not in " ".join(args)
    assert (film.parent / "master_audio.wav").is_file()
    assert (film.parent / "master_audio_final.m4a").is_file()
    probe = probe_media_file(film)
    assert probe["ok"] and probe["has_audio"]


@requires_ffmpeg
def test_a_dynamic_loudness_pass_is_written_down_for_the_owner(engine, tmp_path, monkeypatch):
    import app.media.assembler as assembler
    from app.media.toolchain import loudnorm_warning

    real = assembler.encode_master_audio

    def dynamic(*args, **kwargs):
        result = real(*args, **kwargs)
        result["normalization_type"] = "dynamic"
        result["warning"] = loudnorm_warning({"normalization_type": "dynamic"})
        return result

    monkeypatch.setattr(assembler, "encode_master_audio", dynamic)
    sb_id, _ = _seeded_storyboard(engine, tmp_path)
    render = assemble_video_job(engine, sb_id, str(uuid4()), storage_root=tmp_path / "media")
    production = render["production"]
    assert production["audio"]["loudness"]["normalization_type"] == "dynamic"
    warning = production["audio"]["loudness"]["warning"]
    assert warning and "dinamic" in warning
    assert warning in production["owner_warnings"]


@requires_ffmpeg
def test_repair_audio_redoes_the_sound_and_copies_the_picture_packet_for_packet(engine, tmp_path):
    import hashlib

    from app.media.assembler import AudioRepairError, repair_audio
    from app.media.toolchain import LOUDNESS_BAND_LUFS, TRUE_PEAK_CEILING_DBTP, measure_loudness

    sb_id, _ = _seeded_storyboard(engine, tmp_path)
    render = assemble_video_job(engine, sb_id, str(uuid4()), storage_root=tmp_path / "media")
    original = Path(render["file_path"])
    original_sha = hashlib.sha256(original.read_bytes()).hexdigest()

    repaired = repair_audio(engine, render["output_asset_id"], str(uuid4()))

    fixed = Path(repaired["file_path"])
    assert fixed != original and fixed.is_file()
    # The picture is the same picture, packet for packet: -c:v copy, no re-encode.
    assert _stream_hash(fixed, "0:v:0") == _stream_hash(original, "0:v:0")
    assert repaired["video_stream_sha256"] == _stream_hash(original, "0:v:0").split("=", 1)[-1]
    # The film it came from is left exactly as it was.
    assert hashlib.sha256(original.read_bytes()).hexdigest() == original_sha

    delivered = measure_loudness(find_ffmpeg(), fixed)
    low, high = LOUDNESS_BAND_LUFS
    assert low <= delivered["integrated_lufs"] <= high
    assert delivered["true_peak_dbtp"] <= TRUE_PEAK_CEILING_DBTP
    assert repaired["credits"] == 0

    with Session(engine) as session:
        asset = session.get(MediaAsset, repaired["output_asset_id"])
        assert asset is not None and asset.uri_or_path == str(fixed)
        assert asset.provenance_hash == hashlib.sha256(fixed.read_bytes()).hexdigest()
        job = session.scalar(
            select(VideoRenderJob).where(
                VideoRenderJob.output_asset_id == repaired["output_asset_id"]
            )
        )
        # Quality control finds the new film's manifest, and the manifest says what it is.
        assert job is not None and job.status == "COMPLETED"
        remaster = job.production_json["remaster"]
        assert remaster["of_asset"] == render["output_asset_id"]
        assert remaster["kind"] == "audio" and remaster["credits"] == 0
        assert job.production_json["audio"]["loudness"]["true_peak_target_dbtp"] == -2.0
        args = list(job.command_args_json)
        assert args[args.index("-c:v") + 1] == "copy"

    # Quality control reads the repaired film as a film, with its sound in band.
    qc = evaluate_media_qc(engine, repaired["output_asset_id"], str(uuid4()))
    assert qc["checks_json"]["audio_qc"]["passed"] is True, qc["checks_json"]["audio_qc"]

    with pytest.raises(AudioRepairError):
        repair_audio(engine, str(uuid4()), str(uuid4()))
