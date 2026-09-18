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


def test_captions_are_sentence_cues_timed_to_each_scenes_narration():
    from app.media.assembler import CAPTION_LINE_CHARS, CAPTION_MAX_LINES, caption_cues

    scenes = [
        {
            "scene_index": 1,
            "duration_seconds": 6.0,
            "audio_seconds": 5.0,
            "voiceover_segment": "Perseverance found layered rock. It points to a river delta.",
        },
        {
            "scene_index": 2,
            "duration_seconds": 6.0,
            "audio_seconds": 4.0,
            "voiceover_segment": "The evidence is conclusive.",
        },
    ]
    cues = caption_cues(scenes)
    # One cue per sentence, in order.
    assert [" ".join(c["lines"]) for c in cues] == [
        "Perseverance found layered rock.",
        "It points to a river delta.",
        "The evidence is conclusive.",
    ]
    # Timed from the scene's audio start over the narration actually recorded for it, not the
    # storyboard's planned length: scene one's words end at 5.0, scene two's start at 6.0.
    assert cues[0]["start"] == 0.0
    assert cues[1]["end"] == pytest.approx(5.0, abs=0.01)
    assert cues[2]["start"] == 6.0 and cues[2]["end"] == pytest.approx(10.0, abs=0.01)
    # Within a scene, time is shared by the sentences' length, so the longer one lasts longer.
    assert (cues[0]["end"] - cues[0]["start"]) > (cues[1]["end"] - cues[1]["start"])
    assert cues[0]["end"] == cues[1]["start"]
    for cue in cues:
        assert 1 <= len(cue["lines"]) <= CAPTION_MAX_LINES
        assert all(len(line) <= CAPTION_LINE_CHARS for line in cue["lines"])
        assert cue["end"] > cue["start"]


def test_a_long_sentence_splits_into_cues_of_two_lines_of_forty_two_characters():
    from app.media.assembler import (
        CAPTION_LINE_CHARS,
        CAPTION_MAX_LINES,
        caption_cues,
        generate_subtitles_srt,
    )
    from app.media.qc import parse_srt

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
    assert len(cues) >= 3, "one sentence of 190 characters cannot fit two lines of 42"
    for cue in cues:
        assert len(cue["lines"]) <= CAPTION_MAX_LINES
        assert all(0 < len(line) <= CAPTION_LINE_CHARS for line in cue["lines"])
    # Nothing is lost or reordered in the split.
    assert _words(" ".join(" ".join(c["lines"]) for c in cues)) == _words(sentence)
    assert cues[0]["start"] == 0.0 and cues[-1]["end"] == pytest.approx(11.5, abs=0.01)

    # The SRT the studio writes is the SRT quality control reads back.
    parsed = parse_srt(generate_subtitles_srt(scenes))
    assert [c["lines"] for c in parsed] == [c["lines"] for c in cues]
    assert parsed[-1]["end"] == pytest.approx(11.5, abs=0.001)

    # A scene with no words has no cue; nothing invents a caption from a visual prompt.
    assert (
        caption_cues([{"scene_index": 1, "duration_seconds": 3.0, "voiceover_segment": ""}]) == []
    )


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
    assert "subtitles=filename=captions.srt" in args
    assert "BorderStyle=1" in args and "PrimaryColour=&H00FFFFFF" in args
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
    assert motion["max_fallback_scenes"] == 2  # half of four, the default
    assert motion["environment"] == "PRODUCTION"
    assert any("fallback" in r.lower() or "push" in r.lower() for r in qc["failure_reasons_json"])

    # The same film in TEST: two motion scenes are policy, the rest push; a warning, no fail.
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "TEST"
    qc = evaluate_media_qc(engine, asset, str(uuid4()))
    motion = qc["checks_json"]["motion_qc"]
    assert motion["passed"] is True and motion["warning"]
    assert not any("fallback" in r.lower() for r in qc["failure_reasons_json"])

    # The Owner's ceiling is read from settings; one refusal over it fails production.
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"
    strict = _render_with_motion_record(engine, tmp_path, refused=1, made=3)
    qc = evaluate_media_qc(
        engine, strict, str(uuid4()), settings=SimpleNamespace(max_fallback_scenes=0)
    )
    assert qc["checks_json"]["motion_qc"]["passed"] is False
    qc = evaluate_media_qc(engine, strict, str(uuid4()))
    assert qc["checks_json"]["motion_qc"]["passed"] is True  # one of four is under half


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
