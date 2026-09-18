"""Phase 5 Media Production services: Character Bible and Storyboard generation."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import ROOT
from app.economy.budget import release_reservation, reserve_spend, settle_reservation
from app.economy.services import EconomyError, record_provider_cost
from app.factual.models import ScriptDraft
from app.factual.services import FactualGateError
from app.integrations.models import Integration
from app.media.models import (
    CharacterBible,
    MediaAsset,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.media.production_policy import estimate_cost_usd
from app.media.schemas import (
    CharacterBibleView,
    StoryboardSceneView,
    StoryboardView,
)
from app.models import OwnerPolicy
from app.providers.media_http import MediaProviderError
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


#: A word that is a title, not a name. The first word of "Dr. Aris Researcher" identifies
#: nobody; the second one does.
_NAME_TITLES = frozenset({"dr", "mr", "mrs", "ms", "prof", "sir", "dl", "dna"})

#: Said once on a storyboard whose every scene shows nobody, so a check that finds no cast
#: can tell "this film has no characters by design" from "nobody listed them". A factual film
#: is usually exactly this: material on screen and a narrator who has no face.
NO_CAST_BY_DESIGN = (
    "no scene in this film shows a studio character: the cast is empty by design, not by "
    "omission — the narrator has no face and the scenes show material, not people"
)

#: Said instead of the above on a board whose scenes never state who is in them although
#: their prose spells names the bible holds. Not "by design": nobody decided this film has
#: no cast — the studio read words it could not be sure of and refused to cast on a guess.
NO_CAST_ONLY_GUESSED = (
    "no scene in this film states who is in it: the names its prose spells were read as a "
    "guess, and a guessed name draws nobody's portrait and refuses no film"
)


def _character_keys(canonical_name: str) -> tuple[str, tuple[str, ...]] | tuple[()]:
    """A canonical name as a scene may write it: the whole name, and the given name alone.

    The bible holds "Sarah Executive" and "Dr. Aris Researcher"; a script writes "Sarah" and
    "Aris". Both count, and nothing shorter: "Executive" on its own names a job, not a person.
    This is the first-name rule `app.story.services.bibles_for_roster` already matches a
    roster member by, without the title that rule keeps by accident.

    Returned as (given name, full forms), because the two are matched under different rules.
    """
    words = [word.strip(" ,.()'\"’") for word in str(canonical_name).split()]
    words = [word for word in words if word]
    if not words:
        return ()
    full = tuple({str(canonical_name).strip(), " ".join(words)})
    given = next((word for word in words if word.lower() not in _NAME_TITLES), "")
    return given, full


def _characters_named_in(
    text: str,
    keys_by_id: dict[str, tuple[str, tuple[str, ...]]],
    *,
    given_names: bool = True,
) -> list[str]:
    """The studio characters this text names, in the order it names them.

    Matched as written, capital and all: a name is a proper noun, and a lower-case word that
    happens to spell one is not a person on screen.

    A given name on its own is not counted when another capitalised word follows it, because
    that word is usually a surname the bible does not hold: a factual film says "the Vera
    Rubin Observatory" and means a telescope, not the studio's Publisher.

    `given_names` is which of the two readings this is. False reads only whole canonical
    names — the strict reading, whose every hit is the text's own statement about a studio
    character. True also reads the bare given name, which was measured on this tree to find
    Elena Fact-Checker in "Hurricane Elena made landfall", Lyra Voice Artist in "Lyra, the
    constellation, rises" and Kael Video Editor in "the Kael river delta". That reading is
    right where the text is a record of a cast and wrong where it is prose, so the caller
    says which it is holding rather than one regex trying to be both.
    """
    import re  # noqa: PLC0415 - only the storyboard's cast reads a scene's prose

    found: list[tuple[int, str]] = []
    for character_id, (given, full) in keys_by_id.items():
        patterns = [rf"(?<![\w-]){re.escape(name)}(?![\w-])" for name in full]
        if given and given_names:
            patterns.append(rf"(?<![\w-]){re.escape(given)}(?![\w-])(?!\s+[A-Z])")
        hits = [match.start() for p in patterns if (match := re.search(p, text))]
        if hits:
            found.append((min(hits), character_id))
    return [character_id for _, character_id in sorted(found)]


def _scene_visual(scene: dict, index: int) -> str:
    """What this scene asks to be shown, whichever word the writer used for it.

    The script writer's scenes say "visual_description"; the demo fixture said
    "visual_prompt". Read in one place because the cast is decided from the same text the
    scene is built with — two readings could disagree about what the picture says.
    """
    return str(
        scene.get("visual_prompt")
        or scene.get("visual_cue")
        or scene.get("visual_description")
        or f"Scene {index}"
    ).strip()


def _scene_cast(
    scene: dict, visual_prompt: str, keys_by_id: dict[str, tuple[str, tuple[str, ...]]]
) -> tuple[list[str], list[str]]:
    """Who is on screen in one factual scene, and who the scene's prose only suggests is.

    Returned as (stated, guessed), because a cast is not a label — it steers a paid render
    towards a stored portrait, it is what the character gate compares the frame with, and it
    refuses the film outright when that character's look is locked and no reference exists.
    Two of those three must never follow a guess, so the two readings are kept apart:

    * **stated** — the writer's own cast list for the scene (the shape the serial's script
      already uses), read by given name because a list of characters is a record of who is
      in the scene; plus whole canonical names in the picture the scene asks for, because
      "Sarah Executive at the window" is the film saying who is at the window.
    * **guessed** — a bare given name in that same prose. It is kept, never acted on: the
      board records it so the gate can look, and so a reader can see what the studio read.

    The narration is deliberately not read at all — in a factual film it is the narrator's
    voice, and a name spoken over a photograph of a telescope puts nobody in the shot.
    """
    # One entry at a time, never the whole list joined into a line. Measured 2026-09-18: the
    # list was read as one string, so the rule that protects "the Vera Rubin Observatory" —
    # a given name followed by another capitalised word is somebody else's surname — saw
    # `["Elena", "Kael"]` as «Elena Kael» and dropped Elena. A scene that stated two studio
    # characters recorded one, and the one it dropped was neither stated nor guessed: her
    # stored portrait was not attached to the paid render, the character gate never compared
    # her, and a locked look would have been invented. The rule is right inside one entry,
    # where the two words really are one name, and was only ever wrong across two of them.
    stated: list[str] = []
    for name in scene.get("characters") or []:
        if not isinstance(name, str):
            continue
        for character_id in _characters_named_in(name, keys_by_id):
            if character_id not in stated:
                stated.append(character_id)
    for character_id in _characters_named_in(visual_prompt, keys_by_id, given_names=False):
        if character_id not in stated:
            stated.append(character_id)
    guessed = [
        character_id
        for character_id in _characters_named_in(visual_prompt, keys_by_id)
        if character_id not in stated
    ]
    return stated, guessed


def generate_storyboard_from_script(
    engine: Engine,
    script_draft_id: str,
    visual_style: str,
    aspect_ratio: str,
    correlation_id: str,
) -> dict:
    """Generate a 9:16 vertical storyboard from an APPROVED script draft.

    Strict Content Gate: rejects unapproved scripts or scripts with unverified claims!

    Every scene also records its cast. Measured 2026-09-18: this function wrote
    `character_ids_json=[]` on every scene of every factual film — the studio's main product —
    so `character_drift_qc` had nothing to compare and reported "no scene in this film lists a
    character" for ever, while only the serial's storyboard ever filled it. A scene that
    states a studio character — the writer's cast list, or the whole canonical name in the
    picture it asks for — now records that character; a scene of landscapes records nobody,
    and the creation event says once whether the empty cast is the film's design or a name
    the studio read and refused to act on. Nothing is invented to give a gate something to
    measure, and nothing the studio merely guessed reaches the column a paid render reads.
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

        # Who is in this film, decided once, before anything is written. The bible is read
        # here and nowhere else in this function: a studio with no characters at all has no
        # cast to find, and the character check already says so in its own words.
        keys_by_id = {
            character.id: keys
            for character in session.scalars(select(CharacterBible))
            if (keys := _character_keys(character.canonical_name))
        }
        casts = [
            _scene_cast(scene, _scene_visual(scene, index), keys_by_id)
            for index, scene in enumerate(scenes_data, start=1)
        ]
        scenes_with_cast = sum(1 for stated, _ in casts if stated)
        # What the prose suggested and the board refused to cast on, by scene index as a
        # string because this is a JSON payload. Kept so the gate can look at a suggested
        # face without the film ever depending on it, and so the reading that produced a
        # cast is readable afterwards rather than re-derived from the prose by a second
        # regex that could disagree with this one.
        guessed_cast = {
            str(index): guessed
            for index, (_stated, guessed) in enumerate(casts, start=1)
            if guessed
        }

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
                # The storyboard's own record of its cast: how many scenes state somebody,
                # which names the prose only suggested, and — when nobody is stated — why
                # there is no cast. A check that finds no character reads this instead of
                # guessing why there is none, and the two reasons are not the same reason:
                # a film of landscapes shows nobody by design, while a film whose prose
                # spelled a name was refused a cast it could not be sure of.
                "scenes_with_cast": scenes_with_cast,
                "guessed_cast": guessed_cast,
                "cast_note": (
                    None
                    if scenes_with_cast
                    else (NO_CAST_ONLY_GUESSED if guessed_cast else NO_CAST_BY_DESIGN)
                ),
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
            vp = _scene_visual(s, idx)
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
                # Only the stated cast is written here. Everything downstream treats this
                # column as the film's own word on who is in the shot: the assembler hands
                # it to the render, the factory turns it into the vendor's referenceImages,
                # and a locked look with no reference refuses the scene from it. A guess
                # may do none of those, so it stays on the creation event.
                character_ids_json=casts[idx - 1][0],
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


def storyboard_cast_record(session: Session, storyboard_id: str) -> dict:
    """What this board's maker decided about its cast: the note, and what it only guessed.

    The storyboard's own record is its creation event: `media.storyboard_created` carries
    what the builder decided about the cast, the way `agent.model_assigned` carries who chose
    an employee's model. Returned as ``{"note": str | None, "guessed": {scene: [id, ...]}}``
    with scene indices as strings, exactly as the payload holds them.

    A board written before any of this was recorded answers the empty record, which is
    "nobody said" — not "nobody is in it". The two must not read the same, because a check
    that reports the second on the evidence of the first certifies something nobody measured.
    """
    from app.models import DomainEvent  # noqa: PLC0415 - read projection only

    payload = session.scalar(
        select(DomainEvent.payload)
        .where(
            DomainEvent.event_type == "media.storyboard_created",
            DomainEvent.aggregate_id == storyboard_id,
        )
        .order_by(DomainEvent.sequence)
        .limit(1)
    )
    payload = payload if isinstance(payload, dict) else {}
    note = payload.get("cast_note")
    written = payload.get("guessed_cast")
    guessed: dict[str, list[str]] = {}
    if isinstance(written, dict):
        for index, ids in written.items():
            if isinstance(ids, list):
                guessed[str(index)] = [cid for cid in ids if isinstance(cid, str)]
    return {"note": str(note) if note else None, "guessed": guessed}


def storyboard_cast_note(session: Session, storyboard_id: str) -> str | None:
    """Why this film has no cast, in its maker's own words; None when it has one.

    A board whose scenes do state characters answers None, and so does one built before the
    note was recorded.
    """
    return storyboard_cast_record(session, storyboard_id)["note"]


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
        # Why this film lists nobody, when its maker decided it shows nobody. Carried beside
        # the view rather than in it, because it is a fact from the ledger, not a column.
        data["cast_note"] = storyboard_cast_note(session, storyboard_id)
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


# ------------------------------------------------------- the characters' reference pictures


#: The slots the bible declares, in the order a turnaround is drawn. A slot holds a stored
#: asset id or null; it never holds a description standing in for an image.
REFERENCE_SLOTS = ("portrait", "full_body", "front", "side", "back")

#: What each slot is a picture of. The words are the studio's, not a model's: the same five
#: framings for every character, so two characters' references differ only in the character.
REFERENCE_FRAMINGS: dict[str, str] = {
    "portrait": "Head-and-shoulders portrait, neutral expression, looking into the lens.",
    "full_body": "Full-body standing pose, head to feet inside the frame, arms relaxed.",
    "front": "Character turnaround sheet, front view, neutral stance, head to feet.",
    "side": "Character turnaround sheet, exact side profile, neutral stance, head to feet.",
    "back": "Character turnaround sheet, seen from directly behind, neutral stance.",
}

#: Where a reference picture is kept: beside the renders, not inside one. A reference outlives
#: every film it is used in, so it does not live in a storyboard's working directory.
REFERENCE_STORAGE_ROOT = ROOT / "backend" / "storage" / "character_references"

#: The frame a reference sheet is asked for. The adapter reports what it actually produced,
#: and that measurement is what the asset records.
REFERENCE_WIDTH = 1024
REFERENCE_HEIGHT = 1536


class ReferenceSetError(ValueError):
    """The reference set was not produced. `reason` is a closed vocabulary the page can match:
    AUTONOMY_STOPPED, NO_CHARACTER, NO_IMAGE_PROVIDER, BUDGET."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class ReferenceRequired(ValueError):
    """A character whose look is locked has no reference picture, so the scene cannot be drawn.

    Drawing it anyway would invent a face for a character whose face is fixed, which is the
    thing the lock exists to prevent. The Owner produces the set; the scene is made after.
    """


def _reference_prompt(row: CharacterBible, slot: str) -> str:
    """One slot's prompt, composed from the bible and nothing else."""
    palette = ", ".join(
        f"{name} {value}" for name, value in sorted((row.palette_json or {}).items())
    )
    parts = [
        f"Character reference sheet of {row.canonical_name}, a single character, "
        "plain neutral grey background, even studio lighting, no text, no logos, no border.",
        REFERENCE_FRAMINGS.get(slot, "Character reference sheet, neutral stance."),
        f"Face and hair: {row.face_hair_desc}.",
        f"Outfit: {row.outfit_desc}.",
    ]
    if row.props_desc:
        parts.append(f"Props: {row.props_desc}.")
    if palette:
        parts.append(f"Palette: {palette}.")
    if row.forbidden_deviations:
        parts.append(f"Never: {row.forbidden_deviations}")
    return " ".join(" ".join(part.split()) for part in parts)


def generate_character_reference_set(
    engine: Engine,
    vault: Any,
    character_id: str,
    correlation_id: str,
    *,
    image_adapter: Any | None = None,
    slots: tuple[str, ...] | None = None,
    storage_root: Path | None = None,
) -> dict:
    """Produce a character's reference pictures through the studio's image provider.

    The Owner's act, never the day's: it spends image credits, so it asks the budget before
    the first slot (`reserve_spend`, the media stage's pattern), refuses under STOP AUTONOMY,
    and settles or releases the hold when it is done. A slot whose generation failed keeps
    what it held — null, in a studio that never had one — and the answer names it; nobody is
    told a picture exists that was not produced.
    """
    with Session(engine) as session:
        policy = session.get(OwnerPolicy, 1)
        if policy and policy.autonomy_stopped:
            raise ReferenceSetError(
                "Oprirea autonomiei este activă; Owner-ul trebuie să o ridice mai întâi.",
                reason="AUTONOMY_STOPPED",
            )
        row = session.get(CharacterBible, character_id)
        if row is None:
            raise ReferenceSetError("Personajul nu există.", reason="NO_CHARACTER")
        declared = tuple(slots or tuple(row.reference_assets_json or {}) or REFERENCE_SLOTS)
        prompts = {slot: _reference_prompt(row, slot) for slot in declared}
        canonical_name = row.canonical_name
        existing = dict(row.reference_assets_json or {})

    from app.media.factory import image_provider  # noqa: PLC0415 - factory imports this module

    adapter = image_adapter or image_provider(engine, vault)
    if adapter is None:
        raise ReferenceSetError(
            "Niciun furnizor de imagini verificat. Alege și verifică o conexiune în "
            "Settings → Video și sunet înainte de a produce referințele.",
            reason="NO_IMAGE_PROVIDER",
        )
    integration_id = getattr(adapter, "integration_id", None)
    model_id = getattr(adapter, "model", None)
    provider_name = getattr(adapter, "PROVIDER_NAME", "UNKNOWN_IMAGE_PROVIDER")

    # What the whole set would cost, from recorded pricing. A model with no recorded price is
    # unpriced — None, never zero — and then the hold is of nothing, which an exceeded budget
    # still refuses, because it cannot value what it was asked for.
    with Session(engine) as session:
        per_image = (
            estimate_cost_usd(session, integration_id, model_id, images=1)
            if integration_id and model_id
            else None
        )
    estimate = per_image * len(declared) if per_image is not None else None
    hold = reserve_spend(
        engine,
        int(round((estimate or 0.0) * 1_000_000)),
        f"referințe {canonical_name}",
        correlation_id,
        note=(
            f"{len(declared)} imagini de referință"
            + ("" if per_image is not None else "; modelul nu are preț stocat")
        ),
    )
    if not hold["allowed"]:
        raise ReferenceSetError(hold["reason"], reason="BUDGET")
    reservation_id = hold.get("reservation_id")

    root = Path(storage_root) if storage_root is not None else REFERENCE_STORAGE_ROOT
    folder = root / character_id
    folder.mkdir(parents=True, exist_ok=True)

    produced: dict[str, dict] = {}
    failed: list[dict] = []
    for slot in declared:
        try:
            result = asyncio.run(
                adapter.generate_image(
                    prompts[slot],
                    width=REFERENCE_WIDTH,
                    height=REFERENCE_HEIGHT,
                    extra={"character_id": character_id, "reference_slot": slot},
                )
            )
        except (MediaProviderError, ValueError, OSError) as exc:
            # One refused slot is one missing picture, not a failed set: the slots that did
            # come back are real references the next render can be drawn from.
            failed.append({"slot": slot, "reason": str(exc)[:300]})
            continue
        suffix = result.format if result.format in ("png", "jpeg", "jpg", "webp") else "bin"
        path = folder / f"{slot}.{suffix}"
        try:
            path.write_bytes(result.image_bytes)
        except OSError as exc:
            failed.append({"slot": slot, "reason": str(exc)[:300]})
            continue
        produced[slot] = {
            "asset_id": str(uuid4()),
            "path": path,
            "bytes": len(result.image_bytes),
            "mime_type": f"image/{'jpeg' if suffix == 'jpg' else suffix}",
            "width": result.width,
            "height": result.height,
            "hash": hashlib.sha256(result.image_bytes).hexdigest(),
        }

    now = utc_now()
    with Session(engine) as session, session.begin():
        row = session.get(CharacterBible, character_id)
        if row is None:  # pragma: no cover - the character was deleted mid-flight
            raise ReferenceSetError("Personajul nu mai există.", reason="NO_CHARACTER")
        slots_now = {slot: existing.get(slot) for slot in declared}
        for slot, made in produced.items():
            event = append_event(
                session,
                "media.character_reference_generated",
                "media_asset",
                made["asset_id"],
                1,
                {
                    "character_id": character_id,
                    "slot": slot,
                    "provider": provider_name,
                    "model_id": model_id,
                    "provenance_hash": made["hash"],
                },
                correlation_id,
            )
            session.add(
                MediaAsset(
                    id=made["asset_id"],
                    asset_type="IMAGE",
                    uri_or_path=str(made["path"]),
                    file_size_bytes=made["bytes"],
                    mime_type=made["mime_type"],
                    width=made["width"],
                    height=made["height"],
                    duration_seconds=None,
                    provider_name=provider_name,
                    remote_job_id=None,
                    license_status="ORIGINAL_AI_GENERATED",
                    provenance_hash=made["hash"],
                    created_at=now,
                    event_id=event.event_id,
                )
            )
            slots_now[slot] = made["asset_id"]
        row.reference_assets_json = slots_now

    # The books come after the pictures: a cost row that cannot be written must not lose a
    # reference that exists on disk.
    recorded = 0
    if per_image is not None and integration_id:
        with Session(engine) as session:
            connection = session.get(Integration, integration_id)
            provider_key = connection.kind if connection is not None else provider_name
        for slot, made in produced.items():
            try:
                record_provider_cost(
                    engine,
                    provider=provider_key,
                    external_reference=(
                        f"character-reference:{character_id}:{slot}:{made['asset_id']}"
                    ),
                    status="ESTIMATED",
                    amount=f"{per_image:.6f}",
                    attribution={
                        "character_id": character_id,
                        "slot": slot,
                        "unit": "image",
                        "model_id": model_id,
                        "images": 1,
                    },
                    correlation_id=correlation_id,
                )
                recorded += 1
            except EconomyError:
                # Already in the books: one slot is charged once.
                continue

    if reservation_id:
        if produced:
            settle_reservation(
                engine,
                reservation_id,
                settled_reference=f"character-reference:{character_id}",
                correlation_id=correlation_id,
            )
        else:
            release_reservation(
                engine, reservation_id, "no reference was produced", correlation_id=correlation_id
            )

    return {
        "character_id": character_id,
        "canonical_name": canonical_name,
        "slots": {
            slot: (produced[slot]["asset_id"] if slot in produced else slots_now.get(slot))
            for slot in declared
        },
        "failed": failed,
        "provider": provider_name,
        "model_id": model_id,
        "cost": {
            # A cost the studio cannot compute is None, never zero.
            "usd": round(per_image * len(produced), 6) if per_image is not None else None,
            "per_image_usd": per_image,
            "priced": per_image is not None,
            "recorded": recorded,
        },
        "reservation_id": reservation_id,
    }


def image_reference_for_scene(engine: Engine, character_ids: list[str] | None) -> dict | None:
    """The reference picture this scene's still must be drawn from, if the cast has one.

    A character whose visual identity is locked *must* be drawn from its reference: without
    one this raises, because the alternative is inventing a face the lock exists to protect.
    A character with no lock and no reference simply has none, and the scene is drawn from
    its prompt as it always was. The first character the writer named decides, so a still is
    never drawn from two faces at once.
    """
    ids = [c for c in (character_ids or []) if isinstance(c, str)]
    if not ids:
        return None
    with Session(engine) as session:
        rows = {
            row.id: row
            for row in session.scalars(select(CharacterBible).where(CharacterBible.id.in_(ids)))
        }
        for character_id in ids:
            row = rows.get(character_id)
            if row is None:
                continue
            locked = bool((row.identity_locks_json or {}).get("visual"))
            slots = row.reference_assets_json or {}
            slot = next((s for s in REFERENCE_SLOTS if slots.get(s)), None)
            asset = session.get(MediaAsset, slots[slot]) if slot else None
            if asset is None:
                if locked:
                    raise ReferenceRequired(
                        f"{row.canonical_name} are înfățișarea blocată și nicio imagine de "
                        f"referință stocată ({character_id}); produ setul de referințe "
                        "înainte de a filma scena."
                    )
                continue
            return {
                "character_id": character_id,
                "canonical_name": row.canonical_name,
                "slot": slot,
                "asset_id": asset.id,
                "path": asset.uri_or_path,
                "mime_type": asset.mime_type,
                "required": locked,
            }
    return None
