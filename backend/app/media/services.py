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
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.media.schemas import (
    CharacterBibleView,
    StoryboardSceneView,
    StoryboardView,
)
from app.models import OwnerPolicy
from app.services import append_event, utc_now

logger = logging.getLogger("studio.media")

DEFAULT_CHARACTERS = [
    {
        "canonical_name": "Sarah Executive",
        "role": "Director",
        "palette_json": {"suit": "#1e3a8a", "tie": "#38bdf8", "hair": "#451a03", "desk": "#854d0e"},
        "face_hair_desc": (
            "Brunette professional bob with warm highlights; expressive determined brown eyes"
        ),
        "outfit_desc": (
            "Crisp navy two-piece executive blazer, white collared shirt, and sky-blue tie"
        ),
        "props_desc": "Mahogany desk, post-it note array, steaming espresso cup, gold nameplate.",
        "role_symbols": "Director / CEO Penthouse Suite, panoramic city view, trendline graphs.",
        "voice_profile_json": {
            "voice_id": "sarah_executive",
            "pitch": 1.0,
            "speed": 1.05,
            "style": "Authoritative/Visionary",
        },
        "personality_json": {
            "traits": ["decisive", "strategic", "calm under pressure"],
            "values": ["verified results", "momentum", "clear ownership"],
            "humor": "dry, rare, aimed at situations rather than people",
            "social_energy": "high in briefings, reserved between them",
            "conflict_style": "names the disagreement, sets a deadline, moves on",
            "strengths": ["prioritises fast", "reads a room"],
            "weaknesses": ["impatient with unverified claims", "over-schedules herself"],
        },
        "speech_style_json": {
            "register": "executive briefing",
            "cadence": "measured, few pauses",
            "sentence_length": "short",
            "vocabulary": "plain business language, no filler jargon",
            "habits": ["states the decision before the reasoning", "asks for the number"],
            "language": "en",
        },
        "expressions_json": {
            "greeting": "Right. Where are we?",
            "agreement": "Good. Ship it.",
            "disagreement": "Not yet. Show me the evidence.",
            "under_pressure": "One thing at a time.",
            "sign_off": "Bring me the numbers tomorrow.",
        },
        "behavior_json": {
            "work_rituals": ["reviews the board before the first meeting"],
            "gestures": ["taps the desk once when a decision lands"],
            "desk_habits": ["espresso cup used as a meeting timer"],
            "likes": ["a short agenda"],
            "dislikes": ["a confident guess presented as a fact"],
        },
        "reference_assets_json": {
            "portrait": None,
            "full_body": None,
            "front": None,
            "side": None,
            "back": None,
        },
        "forbidden_deviations": "Do not depict Sarah in casual athletic wear or disheveled hair.",
    },
    {
        "canonical_name": "Dr. Aris Researcher",
        "role": "LeadResearcher",
        "palette_json": {
            "coat": "#f8fafc",
            "shirt": "#0d9488",
            "hair": "#334155",
            "glasses": "#e2e8f0",
        },
        "face_hair_desc": (
            "Dark hair with silver temples; thin circular silver spectacles with white lens glare"
        ),
        "outfit_desc": "Immaculate white laboratory scientist coat over teal button-down shirt.",
        "props_desc": (
            "Ultrawide scientific terminal, stack of verified reference books, digital stylus"
        ),
        "role_symbols": "Research & Fact-Check Lab, holographic network graph whiteboard.",
        "voice_profile_json": {
            "voice_id": "dr_aris_narrator",
            "pitch": 0.95,
            "speed": 0.98,
            "style": "Scientific/Inquisitive",
        },
        "personality_json": {
            "traits": ["curious", "methodical", "quietly stubborn"],
            "values": ["traceable sources", "admitting uncertainty"],
            "humor": "gentle, often at his own expense",
            "social_energy": "low; warms up on a good question",
            "conflict_style": "asks for the source instead of arguing",
            "strengths": ["finds the primary document"],
            "weaknesses": ["goes deeper than the deadline allows"],
        },
        "speech_style_json": {
            "register": "explanatory",
            "cadence": "unhurried, with thinking pauses",
            "sentence_length": "medium, often with a qualifier",
            "vocabulary": "precise, defines a term before using it",
            "habits": ["says where a fact came from", "flags confidence out loud"],
            "language": "en",
        },
        "expressions_json": {
            "greeting": "I found something interesting.",
            "agreement": "That holds up.",
            "disagreement": "Where does that come from?",
            "under_pressure": "Give me one more source.",
            "sign_off": "I will write it up with the citations.",
        },
        "behavior_json": {
            "work_rituals": ["re-reads the source before quoting it"],
            "gestures": ["pushes the glasses up when concentrating"],
            "desk_habits": ["reference books stacked by topic, not by size"],
            "likes": ["a primary document"],
            "dislikes": ["a claim with no origin"],
        },
        "reference_assets_json": {
            "portrait": None,
            "full_body": None,
            "front": None,
            "side": None,
            "back": None,
        },
        "forbidden_deviations": (
            "Do not omit circular glasses; do not portray as unconfident or guessing"
        ),
    },
    {
        "canonical_name": "Elena Fact-Checker",
        "role": "FactChecker",
        "palette_json": {
            "vest": "#4d7c0f",
            "bun": "#78350f",
            "glasses": "#94a3b8",
            "ledger": "#b45309",
        },
        "face_hair_desc": (
            "Auburn hair pulled tightly into a neat high bun; reading glasses perched on nose"
        ),
        "outfit_desc": "Olive utility vest over cream blouse with verification check badge.",
        "props_desc": "Dual verification terminal, physical claim checklist, yellow highlighter.",
        "role_symbols": "Fact-Check Station, evidence audit binders, live confirmation checkmarks.",
        "voice_profile_json": {
            "voice_id": "elena_verifier",
            "pitch": 1.05,
            "speed": 1.02,
            "style": "Precise/Rigorous",
        },
        "personality_json": {
            "traits": ["rigorous", "direct", "unflappable"],
            "values": ["nothing passes unchecked", "the checklist is the job"],
            "humor": "deadpan one-liners",
            "social_energy": "moderate; more talkative once the list is clear",
            "conflict_style": "holds the line on the standard, not on the person",
            "strengths": ["spots the unsupported sentence"],
            "weaknesses": ["reluctant to approve anything at speed"],
        },
        "speech_style_json": {
            "register": "checklist",
            "cadence": "clipped",
            "sentence_length": "short",
            "vocabulary": "concrete, avoids hedging words",
            "habits": ["numbers her points", "repeats the claim before judging it"],
            "language": "en",
        },
        "expressions_json": {
            "greeting": "What am I checking?",
            "agreement": "Verified. Next.",
            "disagreement": "That one is not supported.",
            "under_pressure": "Faster is not the same as checked.",
            "sign_off": "Three verified, one sent back.",
        },
        "behavior_json": {
            "work_rituals": ["prints the claim list and ticks it by hand"],
            "gestures": ["caps and uncaps the highlighter while reading"],
            "desk_habits": ["two screens: claim on the left, source on the right"],
            "likes": ["a claim with a link"],
            "dislikes": ["being asked to approve before she has read it"],
        },
        "reference_assets_json": {
            "portrait": None,
            "full_body": None,
            "front": None,
            "side": None,
            "back": None,
        },
        "forbidden_deviations": (
            "Never approve unverified claims; do not remove hair bun in studio scenes"
        ),
    },
    {
        "canonical_name": "Marcus Scriptwriter",
        "role": "ScriptWriter",
        "palette_json": {
            "hoodie": "#7c3aed",
            "hair": "#1e293b",
            "jeans": "#334155",
            "yarn": "#ef4444",
        },
        "face_hair_desc": "Tousled wavy dark hair; creative focused gaze, slight 5 o clock shadow.",
        "outfit_desc": "Comfortable royal purple fleece hoodie over grey crew tee.",
        "props_desc": (
            "Mechanical keyboard laptop, cork storyboard wall pinned "
            "with colorful index cards and red yarn"
        ),
        "role_symbols": "Creative Writing & Narrative Studio, screenplays, coffee carafe.",
        "voice_profile_json": {
            "voice_id": "marcus_narrative",
            "pitch": 0.98,
            "speed": 1.08,
            "style": "Dynamic/Storyteller",
        },
        "personality_json": {
            "traits": ["inventive", "restless", "generous with ideas"],
            "values": ["a hook that earns the next line", "no filler"],
            "humor": "playful, quick, a little absurd",
            "social_energy": "high; thinks out loud",
            "conflict_style": "offers three alternatives instead of defending one",
            "strengths": ["finds the angle nobody tried"],
            "weaknesses": ["rewrites a working draft one time too many"],
        },
        "speech_style_json": {
            "register": "writers' room",
            "cadence": "fast, with mid-sentence restarts",
            "sentence_length": "varied, often fragments",
            "vocabulary": "vivid, concrete images",
            "habits": ["pitches out loud", "reads lines back in the voice they are for"],
            "language": "en",
        },
        "expressions_json": {
            "greeting": "Okay, hear me out.",
            "agreement": "Yes, and the ending gets better.",
            "disagreement": "The hook dies there.",
            "under_pressure": "Give me one more pass.",
            "sign_off": "Draft is on the board.",
            "recurring_joke": "claims every draft is 'the short one'",
        },
        "behavior_json": {
            "work_rituals": ["pins the beats on the cork wall before writing"],
            "gestures": ["spins the pen while thinking"],
            "desk_habits": ["index cards and red yarn within reach"],
            "likes": ["a strong first line"],
            "dislikes": ["a script that explains its own joke"],
        },
        "reference_assets_json": {
            "portrait": None,
            "full_body": None,
            "front": None,
            "side": None,
            "back": None,
        },
        "forbidden_deviations": (
            "Do not depict wearing formal suits; maintain creative storyteller persona"
        ),
    },
    {
        "canonical_name": "Lyra Voice Artist",
        "role": "VoiceArtist",
        "palette_json": {
            "headphones": "#f43f5e",
            "sweater": "#ec4899",
            "hair": "#0f172a",
            "foam": "#1e1b4b",
        },
        "face_hair_desc": (
            "Sleek jet-black hair with neon pink streak; expressive warm facial features"
        ),
        "outfit_desc": "Fuchsia sound-booth sweater, large over-ear studio monitoring headphones.",
        "props_desc": (
            "Articulated boom condenser microphone with round pop filter, "
            "digital audio workstation display"
        ),
        "role_symbols": (
            "Audio & Vocal Booth, pyramid acoustic foam tiles, active LED EQ waveform meter"
        ),
        "voice_profile_json": {
            "voice_id": "lyra_studio",
            "pitch": 1.02,
            "speed": 1.0,
            "style": "Warm/Broadcast/Engaging",
        },
        "personality_json": {
            "traits": ["warm", "attentive", "perfectionist about takes"],
            "values": ["the listener's ear", "a clean room tone"],
            "humor": "light and inclusive",
            "social_energy": "high one-to-one, quiet in the booth",
            "conflict_style": "asks for the intent, then offers two readings",
            "strengths": ["matches tone to audience"],
            "weaknesses": ["re-records a take that was already good"],
        },
        "speech_style_json": {
            "register": "broadcast warm",
            "cadence": "even, breath-aware",
            "sentence_length": "medium",
            "vocabulary": "conversational, listener-facing",
            "habits": ["marks the breath points in a script", "asks who is listening"],
            "language": "en",
        },
        "expressions_json": {
            "greeting": "Ready when you are.",
            "agreement": "That reads beautifully.",
            "disagreement": "That line will trip the ear.",
            "under_pressure": "One clean take, then we move.",
            "sign_off": "Room tone recorded, we are done.",
        },
        "behavior_json": {
            "work_rituals": ["warms up before the first take"],
            "gestures": ["one hand on the headphone cup while listening back"],
            "desk_habits": ["water and a marked-up script on the stand"],
            "likes": ["a script written for the ear"],
            "dislikes": ["a sentence that cannot be said in one breath"],
        },
        "reference_assets_json": {
            "portrait": None,
            "full_body": None,
            "front": None,
            "side": None,
            "back": None,
        },
        "forbidden_deviations": "Do not depict without studio headphones around neck or on ears.",
    },
    {
        "canonical_name": "Kael Video Editor",
        "role": "VideoEditor",
        "palette_json": {
            "headset": "#06b6d4",
            "shirt": "#ea580c",
            "hair": "#d97706",
            "pc": "#0284c7",
        },
        "face_hair_desc": (
            "Sandy blonde spiky hair; focused concentration, single-ear comms headset"
        ),
        "outfit_desc": "Amber work shirt with rolled-up sleeves, dark cargo pants.",
        "props_desc": (
            "Triple ultrawide curved monitors showing Premiere/FFmpeg timelines, "
            "RGB liquid-cooled tower"
        ),
        "role_symbols": "Video & Render Bay, timeline tracks, color grading palettes.",
        "voice_profile_json": {
            "voice_id": "kael_editor",
            "pitch": 0.92,
            "speed": 1.05,
            "style": "Technical/Energetic",
        },
        "personality_json": {
            "traits": ["technical", "energetic", "blunt about constraints"],
            "values": ["the cut serves the story", "nothing ships broken"],
            "humor": "fast, nerdy, harmless",
            "social_energy": "moderate; talkative about craft",
            "conflict_style": "shows the timeline instead of arguing about it",
            "strengths": ["finds the frame the cut needed"],
            "weaknesses": ["tinkers with grading past the point of return"],
        },
        "speech_style_json": {
            "register": "control room",
            "cadence": "quick, clipped",
            "sentence_length": "short",
            "vocabulary": "tool and timecode terms, explained when asked",
            "habits": ["quotes durations to the second", "narrates what he is about to try"],
            "language": "en",
        },
        "expressions_json": {
            "greeting": "What is the runtime?",
            "agreement": "That cut works.",
            "disagreement": "The picture will drift from the voice there.",
            "under_pressure": "Render is running, do not touch it.",
            "sign_off": "Exported and checked.",
        },
        "behavior_json": {
            "work_rituals": ["watches the whole cut once before touching it"],
            "gestures": ["scrubs the timeline back and forth while thinking"],
            "desk_habits": ["one headphone on, one off"],
            "likes": ["a clean source file"],
            "dislikes": ["a last-minute change after the render starts"],
        },
        "reference_assets_json": {
            "portrait": None,
            "full_body": None,
            "front": None,
            "side": None,
            "back": None,
        },
        "forbidden_deviations": (
            "Never depict editing on a tiny laptop; always triple-screen workstation"
        ),
    },
    {
        "canonical_name": "Vera Distribution Hub",
        "role": "Publisher",
        "palette_json": {
            "console": "#22c55e",
            "suit": "#065f46",
            "hair": "#1c1917",
            "radar": "#4ade80",
        },
        "face_hair_desc": "Short styled black hair; sharp alert eyes, mission-control headset.",
        "outfit_desc": "Forest green technical flight suit with studio telemetry insignia.",
        "props_desc": (
            "Mission control console, global radar projection showing worldwide publication nodes"
        ),
        "role_symbols": (
            "Distribution Hub, live uplink satellite dish telemetry, release authorization buttons"
        ),
        "voice_profile_json": {
            "voice_id": "vera_comms",
            "pitch": 1.0,
            "speed": 1.1,
            "style": "Crisp/Operational",
        },
        "personality_json": {
            "traits": ["crisp", "procedural", "steady in an incident"],
            "values": ["nothing publishes unapproved", "an audit trail for every release"],
            "humor": "dry, mission-control flavoured",
            "social_energy": "moderate; formal on the channel, warmer off it",
            "conflict_style": "states the rule, escalates rather than improvises",
            "strengths": ["keeps the release order straight under load"],
            "weaknesses": ["reluctant to make an exception even when asked nicely"],
        },
        "speech_style_json": {
            "register": "operations channel",
            "cadence": "steady, evenly spaced",
            "sentence_length": "short, status-first",
            "vocabulary": "status and state words, no adjectives",
            "habits": ["reads back what was confirmed", "gives the state before the detail"],
            "language": "en",
        },
        "expressions_json": {
            "greeting": "Queue status?",
            "agreement": "Confirmed, releasing.",
            "disagreement": "That is not approved yet.",
            "under_pressure": "Hold. I will confirm before anything goes out.",
            "sign_off": "Published and logged.",
        },
        "behavior_json": {
            "work_rituals": ["reads the approval record before every release"],
            "gestures": ["one finger held up while waiting for a confirmation"],
            "desk_habits": ["release checklist taped beside the console"],
            "likes": ["an approval with a timestamp"],
            "dislikes": ["a publish request that arrives without one"],
        },
        "reference_assets_json": {
            "portrait": None,
            "full_body": None,
            "front": None,
            "side": None,
            "back": None,
        },
        "forbidden_deviations": (
            "Do not omit telemetry headset; operations console must always be active"
        ),
    },
]


#: Narrative fields the seed may complete on an entry that predates them.
DEFAULT_CHARACTERS.append(
    {
        "canonical_name": "Nadia Accountant",
        "role": "Accountant",
        "palette_json": {
            "blouse": "#7c3aed",
            "cardigan": "#2e1065",
            "hair": "#3f2a1d",
            "ledger": "#14532d",
        },
        "face_hair_desc": (
            "Chestnut hair in a low bun, round tortoiseshell glasses; attentive hazel eyes"
        ),
        "outfit_desc": "Plum blouse under a dark violet cardigan, small brass pen on a chain",
        "props_desc": (
            "Green ledger book, a calculator with a paper roll, a jar of sharpened pencils."
        ),
        "role_symbols": (
            "Accounting & Treasury office, filing cabinets, a wall board of the month's spend."
        ),
        "voice_profile_json": {
            "voice_id": "nadia_books",
            "pitch": 1.0,
            "speed": 0.95,
            "style": "Precise/Unhurried",
        },
        "personality_json": {
            "traits": ["exact", "unhurried", "quietly firm"],
            "values": ["a number that is in the books", "a budget that means something"],
            "humor": "gentle, usually about round numbers",
            "social_energy": "low; prefers the ledger to the meeting",
            "conflict_style": "shows the figure, waits, repeats the figure",
            "strengths": ["remembers every invoice", "never rounds in the studio's favour"],
            "weaknesses": ["slow to accept an estimate", "uneasy with anything unpriced"],
        },
        "speech_style_json": {
            "register": "bookkeeping report",
            "cadence": "even, with a pause before each amount",
            "sentence_length": "short",
            "vocabulary": "amounts, references, periods; no adjectives about money",
            "habits": ["says the amount, then the reference", "names the period every time"],
            "language": "en",
        },
        "expressions_json": {
            "greeting": "The books are open.",
            "agreement": "Recorded, with the reference.",
            "disagreement": "That figure is not in the books.",
            "under_pressure": "One entry at a time. Nothing posts twice.",
            "sign_off": "Closed for the day; the totals are yours.",
        },
        "behavior_json": {
            "work_rituals": ["closes the day before reading anything else"],
            "gestures": ["taps the ledger twice when a total balances"],
            "desk_habits": ["the calculator roll is never torn off before the month ends"],
            "likes": ["an invoice that matches its estimate"],
            "dislikes": ["a render with no price on it"],
        },
        "reference_assets_json": {
            "portrait": None,
            "full_body": None,
            "front": None,
            "side": None,
            "back": None,
        },
        "forbidden_deviations": (
            "Do not depict Nadia without her glasses or with a laptop in place of the ledger."
        ),
    }
)

PERSONA_FIELDS = (
    "personality_json",
    "speech_style_json",
    "expressions_json",
    "behavior_json",
    "reference_assets_json",
)


def seed_default_character_bibles(engine: Engine) -> int:
    """Pre-populate Character Bible with default studio employees if empty.

    Returns how many rows were written: inserts, plus narrative fields completed on rows that
    were seeded before those fields existed. Idempotent, so it is safe on every read.
    """
    from app.agents.models import Agent, Role

    with Session(engine) as session, session.begin():
        count = 0
        # The employee each character is: the active agent holding the character's role.
        # Filled only while empty, so an Owner's own assignment is never replaced.
        agents_by_role = {
            role.name: agent.id
            for agent, role in session.execute(
                select(Agent, Role)
                .join(Role, Agent.role_id == Role.id)
                .where(Agent.lifecycle == "ACTIVE")
            ).all()
        }
        for char_data in DEFAULT_CHARACTERS:
            existing = session.scalar(
                select(CharacterBible).where(
                    CharacterBible.canonical_name == char_data["canonical_name"]
                )
            )
            employee_id = agents_by_role.get(char_data.get("role", ""))
            if not existing:
                char_id = str(uuid4())
                bible = CharacterBible(
                    id=char_id,
                    employee_id=employee_id,
                    canonical_name=char_data["canonical_name"],
                    palette_json=char_data["palette_json"],
                    face_hair_desc=char_data["face_hair_desc"],
                    outfit_desc=char_data["outfit_desc"],
                    props_desc=char_data["props_desc"],
                    role_symbols=char_data["role_symbols"],
                    voice_profile_json=char_data["voice_profile_json"],
                    personality_json=char_data["personality_json"],
                    speech_style_json=char_data["speech_style_json"],
                    expressions_json=char_data["expressions_json"],
                    behavior_json=char_data["behavior_json"],
                    reference_assets_json=char_data["reference_assets_json"],
                    forbidden_deviations=char_data["forbidden_deviations"],
                    version=1,
                    created_at=utc_now(),
                    event_id=None,
                )
                session.add(bible)
                count += 1
            else:
                # A row seeded before the persona fields existed is completed here, once.
                # Only empty fields are filled: an edited bible is never overwritten.
                for field in PERSONA_FIELDS:
                    if not getattr(existing, field):
                        setattr(existing, field, char_data[field])
                        count += 1
                if existing.employee_id is None and employee_id:
                    existing.employee_id = employee_id
                    count += 1
        return count


def list_character_bibles(engine: Engine) -> list[dict]:
    with Session(engine) as session:
        chars = session.scalars(
            select(CharacterBible).order_by(CharacterBible.canonical_name)
        ).all()
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
                f"Cannot generate storyboard for script with status {script.status!r}; "
                f"must be 'APPROVED'.",
                [],
            )

        if script.unverified_claim_ids_json:
            raise FactualGateError(
                f"Script contains {len(script.unverified_claim_ids_json)} unverified claims; "
                f"blocked by Content Gate.",
                list(script.unverified_claim_ids_json),
            )

        # One live storyboard per script: an earlier one nobody has rendered is superseded
        # by this rebuild (a placeholder board from a key mismatch, a board the Owner wants
        # redone), so the render stage never picks the stale one over the new.
        rendered_boards = set(
            session.scalars(
                select(VideoRenderJob.storyboard_id).where(VideoRenderJob.status == "COMPLETED")
            )
        )
        for earlier in session.scalars(
            select(Storyboard).where(
                Storyboard.script_draft_id == script_draft_id, Storyboard.status == "APPROVED"
            )
        ):
            if earlier.id not in rendered_boards:
                earlier.status = "REJECTED"

        scenes_data = script.scenes_json or []
        if not scenes_data:
            # Fallback single scene from voiceover text if scenes_json empty
            scenes_data = [
                {
                    "scene_index": 1,
                    "visual_prompt": f"Opening scene illustrating: {script.title}",
                    "visual_type": "MOTION_GRAPHIC",
                    "duration_seconds": float(script.target_duration_seconds),
                    "voiceover_segment": script.voiceover_full_text,
                    "shot_type": "MEDIUM",
                    "transition_in": "FADE",
                    "claim_ids": script.claim_ids_json,
                }
            ]

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
            # The script writer's scenes say "narration" and "visual_description"; the demo
            # fixture said "voiceover_segment" and "visual_prompt". Reading only the latter
            # built a storyboard of eight silent scenes called "Scene 1"… "Scene 8" from a
            # real script, and the voice artist passed it: nothing to pronounce.
            vo = str(
                s.get("voiceover_segment") or s.get("voiceover") or s.get("narration") or ""
            ).strip()
            vp = str(
                s.get("visual_prompt")
                or s.get("visual_cue")
                or s.get("visual_description")
                or f"Scene {idx}"
            ).strip()
            # Without a stated duration a scene lasts as long as its words take to say
            # (about 2.5 a second), within what a short's scene can hold.
            dur = float(s.get("duration_seconds") or 0) or min(
                9.0, max(3.0, round(len(vo.split()) / 2.5, 1))
            )
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


def list_scripts_awaiting_storyboard(engine: Engine) -> list[dict]:
    """Approved scripts that no storyboard has been built from yet.

    This is the handover between research and production. It exists because the two halves of
    the studio were only joined by a demo fixture: an Owner who had just approved a real script
    had no way to carry it into production, and the only creation path in the interface produced
    test data. Only APPROVED drafts appear — the factual gate is what approval represents, and
    offering an unapproved one here would invite starting production on unverified claims.
    """
    with Session(engine) as session:
        built = set(session.scalars(select(Storyboard.script_draft_id)).all())
        drafts = session.scalars(
            select(ScriptDraft)
            .where(ScriptDraft.status == "APPROVED")
            .order_by(ScriptDraft.created_at.desc())
        ).all()
        return [
            {
                "id": draft.id,
                "topic_id": draft.topic_id,
                "title": draft.title,
                "version": draft.version,
                "target_duration_seconds": draft.target_duration_seconds,
                "scene_count": len(draft.scenes_json or []),
                "claim_count": len(draft.claim_ids_json or []),
                "created_at": draft.created_at,
            }
            for draft in drafts
            if draft.id not in built
        ]


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
        data = view.model_dump()
        # What the last render of this storyboard decided about motion: which model filmed
        # each scene, in which environment, what it cost, and what the router did not buy.
        # A decision the Owner cannot read is a decision he has to take on trust.
        job = session.scalars(
            select(VideoRenderJob)
            .where(VideoRenderJob.storyboard_id == storyboard_id)
            .order_by(VideoRenderJob.started_at.desc())
        ).first()
        production = job.production_json if job and isinstance(job.production_json, dict) else {}
        data["motion"] = production.get("motion")
        data["motion_notes"] = production.get("motion_notes") or []
        data["motion_scenes"] = [
            {"scene_index": entry.get("scene_index"), **(entry.get("motion") or {})}
            for entry in production.get("scenes") or []
            if isinstance(entry, dict) and isinstance(entry.get("motion"), dict)
        ]
        return data


def list_storyboards(engine: Engine) -> list[dict]:
    with Session(engine) as session:
        storyboards = session.scalars(
            select(Storyboard).order_by(Storyboard.created_at.desc())
        ).all()
        result = []
        for sb in storyboards:
            view = StoryboardView.model_validate(sb)
            result.append(view.model_dump())
        return result
