"""Phase 5 Media Production services: Character Bible and Storyboard generation."""

from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.factual.models import ScriptDraft
from app.factual.services import FactualGateError
from app.media.models import (
    CharacterBible,
    MediaAsset,
    QualityControlReport,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.media.schemas import (
    CharacterBibleView,
    CreateCharacterBibleCommand,
    StoryboardSceneView,
    StoryboardView,
)
from app.models import OwnerPolicy
from app.services import append_event, utc_now

logger = logging.getLogger("studio.media")

DEFAULT_CHARACTERS = [
    {
        "canonical_name": "Sarah Executive",
        "palette_json": {"suit": "#1e3a8a", "tie": "#38bdf8", "hair": "#451a03", "desk": "#854d0e"},
        "face_hair_desc": "Brunette professional bob with warm highlights; expressive determined brown eyes.",
        "outfit_desc": "Crisp navy two-piece executive blazer, white collared shirt, and sky-blue tie.",
        "props_desc": "Mahogany desk, post-it note array, steaming espresso cup, gold nameplate.",
        "role_symbols": "Director / CEO Penthouse Suite, panoramic city view, trendline graphs.",
        "voice_profile_json": {"voice_id": "sarah_executive", "pitch": 1.0, "speed": 1.05, "style": "Authoritative/Visionary"},
        "forbidden_deviations": "Do not depict Sarah in casual athletic wear or disheveled hair.",
    },
    {
        "canonical_name": "Dr. Aris Researcher",
        "palette_json": {"coat": "#f8fafc", "shirt": "#0d9488", "hair": "#334155", "glasses": "#e2e8f0"},
        "face_hair_desc": "Dark hair with silver temples; thin circular silver spectacles with white lens glare.",
        "outfit_desc": "Immaculate white laboratory scientist coat over teal button-down shirt.",
        "props_desc": "Ultrawide scientific terminal, stack of verified reference books, digital stylus.",
        "role_symbols": "Research & Fact-Check Lab, holographic network graph whiteboard.",
        "voice_profile_json": {"voice_id": "dr_aris_narrator", "pitch": 0.95, "speed": 0.98, "style": "Scientific/Inquisitive"},
        "forbidden_deviations": "Do not omit circular glasses; do not portray as unconfident or guessing.",
    },
    {
        "canonical_name": "Elena Fact-Checker",
        "palette_json": {"vest": "#4d7c0f", "bun": "#78350f", "glasses": "#94a3b8", "ledger": "#b45309"},
        "face_hair_desc": "Auburn hair pulled tightly into a neat high bun; reading glasses perched on nose.",
        "outfit_desc": "Olive utility vest over cream blouse with verification check badge.",
        "props_desc": "Dual verification terminal, physical claim checklist, yellow highlighter.",
        "role_symbols": "Fact-Check Station, evidence audit binders, live confirmation checkmarks.",
        "voice_profile_json": {"voice_id": "elena_verifier", "pitch": 1.05, "speed": 1.02, "style": "Precise/Rigorous"},
        "forbidden_deviations": "Never approve unverified claims; do not remove hair bun in studio scenes.",
    },
    {
        "canonical_name": "Marcus Scriptwriter",
        "palette_json": {"hoodie": "#7c3aed", "hair": "#1e293b", "jeans": "#334155", "yarn": "#ef4444"},
        "face_hair_desc": "Tousled wavy dark hair; creative focused gaze, slight 5 o clock shadow.",
        "outfit_desc": "Comfortable royal purple fleece hoodie over grey crew tee.",
        "props_desc": "Mechanical keyboard laptop, cork storyboard wall pinned with colorful index cards and red yarn.",
        "role_symbols": "Creative Writing & Narrative Studio, screenplays, coffee carafe.",
        "voice_profile_json": {"voice_id": "marcus_narrative", "pitch": 0.98, "speed": 1.08, "style": "Dynamic/Storyteller"},
        "forbidden_deviations": "Do not depict wearing formal suits; maintain creative storyteller persona.",
    },
    {
        "canonical_name": "Lyra Voice Artist",
        "palette_json": {"headphones": "#f43f5e", "sweater": "#ec4899", "hair": "#0f172a", "foam": "#1e1b4b"},
        "face_hair_desc": "Sleek jet-black hair with neon pink streak; expressive warm facial features.",
        "outfit_desc": "Fuchsia sound-booth sweater, large over-ear studio monitoring headphones.",
        "props_desc": "Articulated boom condenser microphone with round pop filter, digital audio workstation display.",
        "role_symbols": "Audio & Vocal Booth, pyramid acoustic foam tiles, active LED EQ waveform meter.",
        "voice_profile_json": {"voice_id": "lyra_studio", "pitch": 1.02, "speed": 1.0, "style": "Warm/Broadcast/Engaging"},
        "forbidden_deviations": "Do not depict without studio headphones around neck or on ears.",
    },
    {
        "canonical_name": "Kael Video Editor",
        "palette_json": {"headset": "#06b6d4", "shirt": "#ea580c", "hair": "#d97706", "pc": "#0284c7"},
        "face_hair_desc": "Sandy blonde spiky hair; focused concentration, single-ear comms headset.",
        "outfit_desc": "Amber work shirt with rolled-up sleeves, dark cargo pants.",
        "props_desc": "Triple ultrawide curved monitors showing Premiere/FFmpeg timelines, RGB liquid-cooled tower.",
        "role_symbols": "Video & Render Bay, timeline tracks, color grading palettes.",
        "voice_profile_json": {"voice_id": "kael_editor", "pitch": 0.92, "speed": 1.05, "style": "Technical/Energetic"},
        "forbidden_deviations": "Never depict editing on a tiny laptop; always triple-screen workstation.",
    },
    {
        "canonical_name": "Vera Distribution Hub",
        "palette_json": {"console": "#22c55e", "suit": "#065f46", "hair": "#1c1917", "radar": "#4ade80"},
        "face_hair_desc": "Short styled black hair; sharp alert eyes, mission-control headset.",
        "outfit_desc": "Forest green technical flight suit with studio telemetry insignia.",
        "props_desc": "Mission control console, global radar projection showing worldwide publication nodes.",
        "role_symbols": "Distribution Hub, live uplink satellite dish telemetry, release authorization buttons.",
        "voice_profile_json": {"voice_id": "vera_comms", "pitch": 1.0, "speed": 1.1, "style": "Crisp/Operational"},
        "forbidden_deviations": "Do not omit telemetry headset; operations console must always be active.",
    },
]


def seed_default_character_bibles(engine: Engine) -> int:
    """Pre-populate Character Bible with default studio employees if empty."""
    with Session(engine) as session, session.begin():
        count = 0
        for char_data in DEFAULT_CHARACTERS:
            existing = session.scalar(
                select(CharacterBible).where(CharacterBible.canonical_name == char_data["canonical_name"])
            )
            if not existing:
                char_id = str(uuid4())
                bible = CharacterBible(
                    id=char_id,
                    employee_id=None,
                    canonical_name=char_data["canonical_name"],
                    palette_json=char_data["palette_json"],
                    face_hair_desc=char_data["face_hair_desc"],
                    outfit_desc=char_data["outfit_desc"],
                    props_desc=char_data["props_desc"],
                    role_symbols=char_data["role_symbols"],
                    voice_profile_json=char_data["voice_profile_json"],
                    forbidden_deviations=char_data["forbidden_deviations"],
                    version=1,
                    created_at=utc_now(),
                    event_id=None,
                )
                session.add(bible)
                count += 1
        return count


def list_character_bibles(engine: Engine) -> list[dict]:
    with Session(engine) as session:
        chars = session.scalars(select(CharacterBible).order_by(CharacterBible.canonical_name)).all()
        return [CharacterBibleView.model_validate(c).model_dump() for c in chars]


def get_character_bible(engine: Engine, character_id: str) -> dict | None:
    with Session(engine) as session:
        c = session.get(CharacterBible, character_id)
        return CharacterBibleView.model_validate(c).model_dump() if c else None


def generate_storyboard_from_script(
    engine: Engine,
    script_draft_id: str,
    visual_style: str,
    aspect_ratio: str,
    correlation_id: str,
) -> dict:
    """Generate a 9:16 vertical storyboard from an APPROVED script draft.

    Strict Content Gate: rejects unapproved scripts or scripts with unverified claims!
    """
    storyboard_id = str(uuid4())
    now = utc_now()

    with Session(engine) as session, session.begin():
        # Check Owner Policy
        policy = session.get(OwnerPolicy, 1)
        if policy and policy.autonomy_stopped:
            raise FactualGateError("Global autonomy stop is active; Owner must clear it first.", [])

        script = session.get(ScriptDraft, script_draft_id)
        if not script:
            raise ValueError(f"Script draft {script_draft_id} not found")

        if script.status != "APPROVED":
            raise FactualGateError(
                f"Cannot generate storyboard for script with status {script.status!r}; must be 'APPROVED'.",
                [],
            )

        if script.unverified_claim_ids_json:
            raise FactualGateError(
                f"Script contains {len(script.unverified_claim_ids_json)} unverified claims; blocked by Content Gate.",
                list(script.unverified_claim_ids_json),
            )

        scenes_data = script.scenes_json or []
        if not scenes_data:
            # Fallback single scene from voiceover text if scenes_json empty
            scenes_data = [{
                "scene_index": 1,
                "visual_prompt": f"Opening scene illustrating: {script.title}",
                "visual_type": "MOTION_GRAPHIC",
                "duration_seconds": float(script.target_duration_seconds),
                "voiceover_segment": script.voiceover_full_text,
                "shot_type": "MEDIUM",
                "transition_in": "FADE",
                "claim_ids": script.claim_ids_json,
            }]

        event = append_event(
            session,
            "media.storyboard_created",
            "storyboard",
            storyboard_id,
            1,
            {
                "script_draft_id": script_draft_id,
                "title": script.title,
                "visual_style": visual_style,
                "aspect_ratio": aspect_ratio,
                "scene_count": len(scenes_data),
            },
            correlation_id,
        )

        sb = Storyboard(
            id=storyboard_id,
            script_draft_id=script_draft_id,
            title=f"Storyboard: {script.title}",
            visual_style=visual_style,
            aspect_ratio=aspect_ratio,
            target_duration_seconds=script.target_duration_seconds,
            status="APPROVED",
            total_scenes=len(scenes_data),
            created_at=now,
            event_id=event.event_id,
        )
        session.add(sb)
        session.flush()

        # Create individual StoryboardScenes
        for idx, s in enumerate(scenes_data, start=1):
            scene_id = str(uuid4())
            dur = float(s.get("duration_seconds", 5.0))
            vo = str(s.get("voiceover_segment", s.get("voiceover", "")))
            vp = str(s.get("visual_prompt", s.get("visual_cue", f"Scene {idx}")))
            st = str(s.get("shot_type", "MEDIUM"))
            tr = str(s.get("transition_in", "CUT"))
            claims = list(s.get("claim_ids", script.claim_ids_json))

            scene_rec = StoryboardScene(
                id=scene_id,
                storyboard_id=storyboard_id,
                scene_index=idx,
                visual_prompt=vp,
                visual_type=visual_style,
                duration_seconds=dur,
                voiceover_segment=vo,
                shot_type=st,
                transition_in=tr,
                character_ids_json=[],
                claim_ids_json=claims,
                created_at=now,
            )
            session.add(scene_rec)

    return get_storyboard(engine, storyboard_id) or {}


def get_storyboard(engine: Engine, storyboard_id: str) -> dict | None:
    with Session(engine) as session:
        sb = session.get(Storyboard, storyboard_id)
        if not sb:
            return None
        scenes = session.scalars(
            select(StoryboardScene)
            .where(StoryboardScene.storyboard_id == storyboard_id)
            .order_by(StoryboardScene.scene_index)
        ).all()
        view = StoryboardView.model_validate(sb)
        view.scenes = [StoryboardSceneView.model_validate(s) for s in scenes]
        return view.model_dump()


def list_storyboards(engine: Engine) -> list[dict]:
    with Session(engine) as session:
        storyboards = session.scalars(select(Storyboard).order_by(Storyboard.created_at.desc())).all()
        result = []
        for sb in storyboards:
            view = StoryboardView.model_validate(sb)
            result.append(view.model_dump())
        return result
