"""From an approved story to the instructions a camera would understand.

What the studio used to send a video model was the line the writer had typed under `visual`:
"a spinning galaxy". Eight of those, at about two dollars sixty a shot, and the Owner's
verdict was exact — "sunt doar niste imagini lipite". Nothing in that pipeline ever described
a camera, a light, a lens, a continuity rule or a reason for the shot to exist, and no amount
of money spent on a better model repairs a prompt that says nothing.

This is the step between the approved script and the generator, and it has two parts:

- **A master visual bible for the film.** One look, decided once: style and realism, the
  world and its period, the palette, how light behaves, the camera's language, the continuity
  rules every shot inherits, and what must never appear. Without it, each shot is a different
  film that happens to be adjacent to the last.
- **A full prompt package per shot.** Subject, action, environment, camera, lighting,
  composition, motion, emotion, background, continuity with the shot before it, audio intent,
  transition, what to avoid — and the story purpose, so a shot that serves nothing can be
  found and cut instead of filmed.

Three rules this step does not bend. It may not invent a fact: a number or a date that is not
in the narration or the claims is refused, because a prompt is not a place to write history.
It may not make the film more spectacular than the story: a quiet last message from a dying
spacecraft does not acquire a battle. And it writes the same package in both environments —
TEST saves money by choosing a cheaper model, never by thinking less. `visual_prompt` keeps
holding what is actually sent, composed from the package, so the entire render path downstream
is unchanged by any of this.

An episode of the office serial takes the same path with its own brief (S8, 2026-09-24). Its
look is not decided per film: the storyboard's bible is the series' one look
(`app.media.series_look`), and every serial prompt opens with its style block word for word,
then the beat's room, the camera, the people in frame as their bibles describe them and the
action, within the look's cap (`compose_serial_prompt`). The model is asked only for the
people: who is in frame facing the viewer, what they do and feel, where the camera stands.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.memory import agent_for_role, remember
from app.db import lock_for_write
from app.factual.editorial import SCENE_PURPOSES
from app.factual.models import FactualClaim, ScriptDraft
from app.factual.sanitizer import wrap_in_inert_boundary
from app.media import prompt_lint as lint
from app.media.models import CharacterBible, Storyboard, StoryboardScene
from app.media.series_look import (
    LIGHT_SLOTS,
    PART_PURPOSES,
    PLACE_SLOTS,
    SHOT_TYPES,
    load_factual_look,
    load_series_look,
    look_block,
    serial_shot_size,
    series_bible,
)
from app.services import append_event, utc_now

logger = logging.getLogger("studio.prompt_agent")

#: The role that owns the studio's pictures. The same steward who reads the vendors' pages
#: about video models writes the instructions those models are given.
PROMPT_ROLE = "VideoEditor"
BIBLE_TEMPLATE = "visual-bible-v1"
SHOTS_TEMPLATE = "shot-prompts-v1"
SERIAL_SHOTS_TEMPLATE = "serial-shot-prompts-v1"

#: The marks of an office-serial film, as `storyboard_from_episode` writes them (the same
#: marks `app.agents.editorial.is_serial_film` reads; that module imports this one).
SERIAL_SERIES_KEY = "office_serial"
SERIAL_SCRIPT_KIND = "office_serial_episode"

#: What the studio will not accept in any generated picture, whatever the story. Not a style
#: preference: these are the failures that make a film look like a raw AI generation.
DEFAULT_NEGATIVES = (
    "on-screen text or captions",
    "warped or extra hands and fingers",
    "plastic or waxy skin",
    "cartoon or 3D-render look when realism is asked for",
    "unmotivated camera movement",
    "clothing, hair or weather changing without reason",
    "faces or bodies morphing mid-shot",
    "watermarks or logos",
)

#: A prompt is specific, not long. A thousand meaningless words teach a model nothing, and
#: the fields that matter get buried. Measured in characters of composed prompt.
MAX_PROMPT_CHARS = 1400
MAX_BIBLE_CHARS = 2400

#: The fields a shot package must actually fill. A prompt missing any of them is a prompt
#: that leaves the decision to the model — which is how a night scene arrives sunlit.
REQUIRED_SHOT_FIELDS = (
    "subject",
    "action",
    "environment",
    "camera",
    "lighting",
    "composition",
    "motion",
)

#: Where prompt lessons are kept. Reuses the studio's own memory rather than a new table: a
#: lesson is a studio-wide fact about how a vendor's model reads instructions.
LESSON_MARKER = "prompt lesson:"


#: What the payload of each call may take, in characters of JSON. Whole claims, lessons and
#: then scenes are dropped to fit (`trim_payload`); nothing is ever sliced mid-string.
MAX_BIBLE_PAYLOAD_CHARS = 12000
MAX_SHOTS_PAYLOAD_CHARS = 16000

#: A storyboard whose model shot plan could not be read, even after the one re-ask. It is
#: not rendered until a plan is written: template prompts are a TEST convenience only.
NEEDS_SHOT_PLAN = "NEEDS_SHOT_PLAN"
#: Why a closed film («Închide filmul», `shooting_sheet.film_is_closed`) is not described
#: again: its status stays REJECTED, so its topic no longer holds the studio.
FILM_CLOSED_PROMPTS_RO = (
    "Filmul este închis: planul lui de cadre nu se mai scrie, iar filmul rămâne închis. "
    "Nimic nu s-a schimbat."
)

#: Where each scene's package came from: the video editor's model, the studio's template
#: (no model reachable; TEST only), or the office serial's fixed look with no model.
SOURCE_MODEL = "model"
SOURCE_TEMPLATE = "template"
SOURCE_SERIES_LOOK = "series_look"


class PromptError(ValueError):
    """The prompt package could not be written; nothing was stored."""


class ShotPlanUnusable(PromptError):
    """The model answered, was asked once more, and shots are still missing.

    The storyboard is NEEDS_SHOT_PLAN and a WARNING event names the scenes; nothing about
    it is rendered until a plan is written.
    """

    def __init__(self, storyboard_id: str, missing: list[int], reason: str) -> None:
        self.storyboard_id = storyboard_id
        self.missing = list(missing)
        super().__init__(reason)


# ------------------------------------------------------------------ the shapes


class VisualBible(BaseModel):
    """The one look the whole film inherits."""

    model_config = ConfigDict(extra="ignore")
    style: str = Field(default="", max_length=300)
    realism: str = Field(default="", max_length=200)
    period: str = Field(default="", max_length=200)
    world: str = Field(default="", max_length=400)
    palette: str = Field(default="", max_length=300)
    lighting: str = Field(default="", max_length=400)
    camera_language: str = Field(default="", max_length=400)
    weather: str = Field(default="", max_length=200)
    continuity_rules: list[str] = Field(default_factory=list, max_length=10)
    avoid: list[str] = Field(default_factory=list, max_length=12)
    season: str = Field(default="", max_length=100)
    # The only place a hex colour is kept: the local card compositor reads it, no image or
    # video model ever does (`_coerce` moves every hex it finds in a prompt-bound field here).
    card_palette: list[str] = Field(default_factory=list, max_length=16)


#: The bible fields whose words can reach a picture prompt. A code in capitals or a hex
#: colour in them is refused (`_coerce`): the Nepal bible's "NEPAL_CLIMATE_CRISIS" and
#: "#2E4A66" were pasted into every prompt and read literally by the image model.
PROMPT_BOUND_BIBLE_FIELDS = (
    "style",
    "realism",
    "period",
    "world",
    "season",
    "palette",
    "lighting",
    "camera_language",
    "weather",
    "continuity_rules",
    "avoid",
)

_HEX_COLOUR = re.compile(r"#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b")
_LABEL_PREFIX = re.compile(r"^[A-Za-z][\w /'-]{0,24}:\s*")


def _hex6(value: str) -> str:
    """A hex colour as the cards read it: '#RRGGBB', upper case."""
    digits = value.lstrip("#").upper()
    if len(digits) == 3:
        digits = "".join(char * 2 for char in digits)
    return f"#{digits}"


def _scrub_codes(text: str) -> str:
    """A bible value with every clause that holds a code or a hex colour taken out.

    A hex inside an otherwise worded clause is removed and the words kept ("slate blue
    (#2E4A66)" is "slate blue"); a clause that is only a label and codes ("primary:
    #2E4A66") goes. The rest keeps its own punctuation.
    """
    pieces = re.split(r"((?<=[.!?])\s+|\s*[;,]\s*)", text)
    kept: list[str] = []
    separator = ""
    for position, piece in enumerate(pieces):
        if position % 2:
            separator = piece
            continue
        cleaned = " ".join(re.sub(r"\(\s*\)", "", _HEX_COLOUR.sub("", piece)).split())
        body = _LABEL_PREFIX.sub("", cleaned)
        if lint.ENUM_CODE.search(cleaned) or not re.search(r"[A-Za-z]", body):
            continue
        if kept:
            kept.append("; " if ";" in separator else ", " if "," in separator else " ")
        kept.append(cleaned)
    return " ".join("".join(kept).split())


class ShotPrompt(BaseModel):
    """One shot, described the way a director would brief a camera crew."""

    model_config = ConfigDict(extra="ignore")
    scene_index: int = Field(ge=1, le=60)
    story_purpose: str = Field(default="", max_length=20)
    subject: str = Field(default="", max_length=400)
    action: str = Field(default="", max_length=500)
    environment: str = Field(default="", max_length=500)
    camera: str = Field(default="", max_length=300)
    lighting: str = Field(default="", max_length=300)
    composition: str = Field(default="", max_length=300)
    motion: str = Field(default="", max_length=400)
    emotion: str = Field(default="", max_length=200)
    background: str = Field(default="", max_length=300)
    continuity: str = Field(default="", max_length=400)
    ending_frame: str = Field(default="", max_length=300)
    audio_intent: str = Field(default="", max_length=200)
    transition: str = Field(default="", max_length=200)
    avoid: list[str] = Field(default_factory=list, max_length=10)
    # One move from prompt_lint.CAMERA_MOVES; anything else is ignored by the compiler.
    camera_move: str = Field(default="", max_length=40)
    # A closer framing of the same picture the edit may cut to inside the scene, for nothing
    # (assembler.plan_second_framings): {"subject", "centre_x", "centre_y"}. Any shape is
    # accepted here and read by _second_framing, so a rough answer never costs the shot.
    second_framing: Any = None


class ShotPack(BaseModel):
    model_config = ConfigDict(extra="ignore")
    shots: list[ShotPrompt] = Field(default_factory=list, max_length=60)


_BIBLE_INSTRUCTIONS = (
    "You are the studio's video editor, and this film has been approved. Before any shot is "
    "described, decide the one look the whole film will have, so the finished piece reads as "
    "a single film rather than several clips that happen to be next to each other. Below is "
    "the story and every scene as data.\n\n"
    "Decide: the visual style and how real it should look; the period and the world; the "
    "colour palette; how light behaves across the film; the camera's language; the weather, "
    "if any; the continuity rules every shot must obey (what stays identical from shot to "
    "shot — a character's face and clothing, a location, a time of day, a palette); and what "
    "must never appear. Respect the physical setting: for an airless scene describe vacuum "
    "and direct sunlight, not terrestrial weather, haze or wind. Vertical 9:16, watched on "
    "a phone: the subject has to stay readable. "
    "Be specific and brief — a rule that could describe any film is not a rule. Write every "
    "value in plain English words, the way a photographer would say it: the place by its "
    "name and what it looks like, the season, the weather, the light, and colours named in "
    "words (slate blue, wet ochre). Never write codes in capitals with underscores and never "
    "hex colour codes: an image model reads them literally. A chart or a title card is drawn "
    "by the studio, not by the model; if the film has one, give its colours as hex codes in "
    "card_palette, the only place a code belongs. Return only "
    'JSON: {"style": "...", "realism": "...", "period": "...", "world": "...", '
    '"season": "...", "palette": "...", "lighting": "...", "camera_language": "...", '
    '"weather": "...", "continuity_rules": ["..."], "avoid": ["..."], '
    '"card_palette": ["#RRGGBB"]}.\n'
)

_SHOTS_INSTRUCTIONS = (
    "You are the studio's video editor. The story below is approved and must not change: "
    "your job is to turn each scene into instructions a camera crew would understand, "
    "inheriting the master visual bible exactly. One primary visual idea per shot — the "
    "audience is watching on a phone.\n\n"
    "For every scene give: the subject (and, where a person appears, enough of their look "
    "that the next shot can match it); the action, described as movement rather than as a "
    "label — not 'walking' but 'walking quickly toward camera, looking back over his "
    "shoulder, coat pulled by the wind'; the environment with the detail that matters and no "
    "decoration; the camera (shot size, angle, lens character, and its movement with a path "
    "and a speed); the lighting, with direction, quality and colour; the "
    "composition for a vertical frame; the motion and how the world responds to it; the "
    "emotion, at a believable intensity; the background life, which must not compete with the "
    "subject; what must match the previous shot (continuity); what the last frame should be "
    "left on; the audio intent; the transition into the next shot; and what to avoid.\n\n"
    "Show the information rather than narrating it twice: if the narration says a storm grew "
    "stronger, the picture shows cloud, wind, water and a reaction, not a caption. Never ask "
    "for writing in the picture — no text overlay, title, label, caption or written number: a "
    "generator draws letters as gibberish or stripes, and text is added in the edit. Do not "
    "add facts, numbers, dates or events that are not in the narration or the claims. Do not "
    "make the film more spectacular than the story: no explosions, crowds, battles or aliens "
    "unless the scene says so. Detailed does not mean long — every phrase must earn its "
    "place.\n\n"
    "The camera: name the shot size (a wide establishing shot, a medium shot, or a detail "
    "of hands, objects or texture; never a close-up of a face) and the lens (24mm wide, "
    "50mm, 85mm compression), and choose exactly one camera_move from this list: dolly in, "
    "dolly out, tracking left, tracking right, crane up, crane down, slow orbit, handheld "
    "drift, aerial drift forward, pedestal up, tilt up, tilt down, slow pan left, slow pan "
    "right, rack focus, static. The movement is ample and specific, the way a film moves, "
    "not a timid zoom: in camera, give the move's path with its speed — where it starts and "
    "where it ends over the clip's seconds (a steady dolly in from the whole room to her "
    "hands on the ledger; a crane up from the bench that reveals the hall). Keep static for "
    "a shot the story holds its breath on, and rack focus only beside a clear action of the "
    "subject. Vary the size and the move across the film; never the same one three scenes "
    "in a row. Optionally give second_framing: a closer framing of the same picture the "
    "editor can cut to halfway through a long scene, at no extra cost — what it shows and "
    "where its centre is, as fractions of the frame's width and height (0 left or top, 1 "
    "right or bottom). In motion, say what the subject does across the clip's seconds, as "
    "verbs (she stands and walks to the window; he turns and hands over the ledger; the "
    "wheel spins; the beam pulses), and what the world does and how fast (curtains lift in "
    "the draught, leaves scatter, cloud rolls, water runs, dust rises, light sweeps across "
    "the wall), without camera words. Ample is not spectacle: nothing happens that the "
    "story does not say, and the shot keeps its one primary visual idea. Name colours in "
    "words, never as hex codes or codes in capitals. When the bible says people's faces must "
    "not be seen, show people only from behind, small and distant, or their hands. Return "
    "only JSON: "
    '{"shots": [{"scene_index": 1, "story_purpose": "HOOK", "subject": "...", '
    '"action": "...", "environment": "...", "camera": "...", "camera_move": "dolly in", '
    '"lighting": "...", "composition": "...", "motion": "...", "emotion": "...", '
    '"background": "...", "continuity": "...", "ending_frame": "...", '
    '"audio_intent": "...", "transition": "...", "avoid": ["..."], '
    '"second_framing": {"subject": "...", "centre_x": 0.5, "centre_y": 0.4}}]}.\n'
)


#: The office serial's brief (S8, 2026-09-24). The factual brief asks for a look to be
#: decided and a world to be described; an episode has both already: the series' look is
#: fixed in config/serial_series_look.json, and every beat is set in one of the studio's own
#: rooms. What a shot of the serial needs from the editor is the people: who is in frame,
#: what they do and feel, and where the camera stands.
_SERIAL_SHOTS_INSTRUCTIONS = (
    "You are the studio's video editor, and this is an approved episode of the studio's own "
    "office serial, Inside The Nexus. The beats are as they will be filmed and must not "
    "change. The series has one look, given below as series_look: it is fixed, it opens every "
    "prompt word for word, and you do not describe style, rendering, light or palette "
    "yourself. Each beat is set in the room its location names, one of the studio's own "
    "rooms, and nowhere else.\n\n"
    "For every beat describe one shot: who is in frame, facing the viewer; what they are "
    "doing, as movement rather than a label, and their expression, both taken from the "
    "line's direction and from what they say; the camera, varied across the episode (an "
    "establishing wide shot for the opening beat, two-shots while people talk, a single or a "
    "close-up for a turn or a reaction); the background life, which must not compete with "
    "the speakers; and what must match the previous shot. What people say is heard, never "
    "drawn. Never ask for writing in the picture: no text, sign, label, title, screen words or "
    "written number, because a generator draws letters as gibberish. Do not add events, "
    "objects or people the beat does not have. Return only JSON: "
    '{"shots": [{"scene_index": 1, "subject": "...", "action": "...", "emotion": "...", '
    '"camera": "...", "background": "...", "continuity": "...", "ending_frame": "...", '
    '"audio_intent": "...", "transition": "..."}]}.\n'
)


# ------------------------------------------------------------------ what the film is


def _is_serial(board: Storyboard, script: ScriptDraft | None) -> bool:
    """Whether a storyboard is an episode of the office serial, by the marks it carries."""
    if str(board.series_key or "").strip().lower() == SERIAL_SERIES_KEY:
        return True
    story = script.story_json if script is not None and isinstance(script.story_json, dict) else {}
    return story.get("kind") == SERIAL_SCRIPT_KIND


def _serial_scene_facts(session: Session, entry: dict[str, Any]) -> dict[str, Any]:
    """What a serial beat adds to a scene's facts: its part, room, lines and background.

    The room is the name the storyboard stored; a storyboard built before it stored one
    (before S8) is given the name from the headquarters' rooms, as the storyboard would.
    """
    room = str(entry.get("location_name") or "").strip()
    if not room and entry.get("location"):
        from app.story.locations import location_name, studio_locations  # noqa: PLC0415

        room = location_name(entry["location"], studio_locations(session, []))
    lines = [
        {
            "speaker": line.get("speaker"),
            "direction": line.get("direction") or "",
            "text": line.get("text") or "",
        }
        for line in entry.get("lines") or []
        if isinstance(line, dict)
    ]
    given = entry.get("speaker_bibles")
    bibles: dict[str, Any] = given if isinstance(given, dict) else {}
    speaker_ids: list[str] = []
    for line in lines:
        bible_id = bibles.get(str(line.get("speaker") or ""))
        if bible_id and bible_id not in speaker_ids:
            speaker_ids.append(str(bible_id))
    return {
        "part": str(entry.get("part") or ""),
        "location": room,
        "lines": lines,
        "speaker_ids": speaker_ids,
        "background": [str(name) for name in entry.get("background") or []],
    }


def _film_facts(session: Session, board: Storyboard) -> dict[str, Any]:
    """The story, its scenes and its characters, as the prompt agent reads them."""
    script = session.get(ScriptDraft, board.script_draft_id)
    scenes = list(
        session.scalars(
            select(StoryboardScene)
            .where(StoryboardScene.storyboard_id == board.id)
            .order_by(StoryboardScene.scene_index)
        )
    )
    claims = (
        {
            row.id: row.claim_text
            for row in session.scalars(
                select(FactualClaim).where(FactualClaim.topic_id == script.topic_id)
            )
        }
        if script
        else {}
    )
    script_scenes = {
        int(entry.get("scene_number") or index): entry
        for index, entry in enumerate(list(script.scenes_json or []) if script else [], start=1)
    }
    characters = {
        row.id: row
        for row in session.scalars(
            select(CharacterBible).where(
                CharacterBible.id.in_(
                    [cid for scene in scenes for cid in (scene.character_ids_json or [])]
                )
            )
        )
    }
    serial = _is_serial(board, script)
    facts: dict[str, Any] = {
        "serial": serial,
        "title": board.title,
        "aspect_ratio": board.aspect_ratio,
        "visual_style": board.visual_style,
        "story": dict(script.story_json or {}) if script else {},
        "target_seconds": board.target_duration_seconds,
        "scenes": [
            {
                "scene_index": scene.scene_index,
                "seconds": scene.duration_seconds,
                "story_purpose": scene.story_purpose
                or str(script_scenes.get(scene.scene_index, {}).get("purpose") or ""),
                "narration": scene.voiceover_segment,
                # The writer's own line about what is seen, from the script — not from
                # `visual_prompt`, which this step overwrites with what it composed. Reading
                # it back would feed a second run its own output, and each pass would drift
                # a little further from what the writer actually asked for.
                "writer_visual": str(
                    script_scenes.get(scene.scene_index, {}).get("visual_description")
                    or (scene.prompt_json or {}).get("writer_visual")
                    or scene.visual_prompt
                ),
                "shot_type": scene.shot_type,
                "claims": [claims.get(cid, "") for cid in (scene.claim_ids_json or [])],
                "characters": [
                    {
                        "id": cid,
                        "name": characters[cid].canonical_name,
                        "face_hair": characters[cid].face_hair_desc,
                        "outfit": characters[cid].outfit_desc,
                        "props": characters[cid].props_desc,
                        "never": characters[cid].forbidden_deviations,
                    }
                    for cid in (scene.character_ids_json or [])
                    if cid in characters
                ],
            }
            for scene in scenes
        ],
    }
    if serial:
        scene_list: list[dict[str, Any]] = facts["scenes"]
        for scene_facts in scene_list:
            entry = script_scenes.get(int(scene_facts["scene_index"]), {})
            scene_facts.update(_serial_scene_facts(session, entry))
    return facts


def _allowed_text(facts: dict[str, Any]) -> str:
    """Everything the film is allowed to state: its narration and its verified claims."""
    parts = [str(facts.get("title") or "")]
    for scene in facts.get("scenes", []):
        parts.append(str(scene.get("narration") or ""))
        parts.extend(str(claim) for claim in scene.get("claims") or [])
    story = facts.get("story") or {}
    parts.extend(str(value) for value in story.values() if isinstance(value, str))
    return " ".join(parts)


def new_numbers(text: str, allowed: str) -> list[str]:
    """Numbers a prompt states that the story never did.

    A prompt is not a place to write history. "Three hundred soldiers" in a shot description,
    where the claims say nothing about how many, is a fabricated fact that the picture then
    makes look documented — and the studio publishes it as fact.
    """
    permitted = set(re.findall(r"\d+", allowed))
    # Years and counts only; a lens ("35mm") or a ratio ("9:16") is craft, not a claim.
    found = re.findall(r"(?<![\w.:/])(\d{2,4})(?![\w.:/%]|mm|fps|k\b)", text)
    return sorted({value for value in found if value not in permitted})


#: Words that ask a picture generator to draw writing. Image and video models draw letters as
#: gibberish — the "theory" pages of the ATLAS film read "Theam Thory Thory" — and a scene that
#: asked for "a text overlay appears: 'Top quark or W boson?'" came back as eleven seconds of
#: stripes, the film's whole payoff. Text belongs to the edit, never to the shot.
_TEXT_REQUEST = re.compile(
    r"text overlay|on[- ]?screen text|\bcaptions?\b|\bsubtitles?\b|title card|\blettering\b|"
    r"\btypography\b|\bheadline\b|(?:reads|reading|says|saying|appears?)\s*:?\s*['\"“‘]",
    re.IGNORECASE,
)


def strip_on_screen_text(text: str) -> str:
    """The description with every clause that asks for writing in the picture removed.

    Clauses are sentences and the parts between ';'. What is kept keeps its own
    punctuation: the text used to be rejoined with spaces, so every ';' vanished and each
    package with one was reported as "repaired" although nothing had been taken out. With
    nothing removed the text comes back as it was (whitespace aside).
    """
    said = " ".join(str(text or "").split())
    pieces = re.split(r"((?<=[.!?])\s+|\s*;\s*)", said)
    kept: list[str] = []
    separator = ""
    removed = False
    for position, piece in enumerate(pieces):
        if position % 2:
            separator = piece
            continue
        if not piece.strip():
            continue
        if _TEXT_REQUEST.search(piece):
            removed = True
            ending = piece.rstrip()[-1:]
            # A removed sentence took its full stop with it; the clause before keeps one.
            if ending in ".!?" and kept and kept[-1][-1:] not in ".!?":
                kept[-1] += ending
            continue
        if kept:
            kept.append("; " if ";" in separator else " ")
        kept.append(piece.strip())
    if not removed:
        return said
    return " ".join("".join(kept).split())


#: A clause that asks for another rendering than the series' look: another medium, another
#: studio's style, another frame. The adversary's pass (2026-09-24) found that a model's
#: action, camera, expression and background reached a serial prompt whole, so one
#: "photorealistic live-action, shot on 35mm film" after the style block pulled the still
#: away from the look the block had just asked for. A lens ("35mm lens") is not a style.
_STYLE_OVERRIDE = re.compile(
    r"(?:photo|hyper|ultra)[- ]?realis\w*|\brealism\b|live[- ]action|real[- ]life footage|"
    r"documentary (?:footage|style)|\bshot on (?:\d+ ?mm )?film\b|\bfilm (?:grain|stock)\b|"
    r"\b\d+ ?mm film\b|\banime\b|\bmanga\b|\bcartoon\w*|\b2d\b|hand[- ]drawn|cel[- ]shad\w*|"
    r"watercolou?r|oil[- ]paint\w*|(?:pencil|charcoal|ink) (?:sketch|drawing)|sketch style|"
    r"pixel[- ]art|claymation|stop[- ]motion|black[- ]and[- ]white|monochrome|\bsepia\b|"
    r"\bnoir\b|\bchibi\b|low[- ]poly|comic[- ]book|\bin the style of\b|"
    r"\b(?:pixar|disney|ghibli|dreamworks)\b|\b16 ?: ?9\b|widescreen|"
    r"horizontal (?:frame|format)|landscape (?:frame|format|orientation)|"
    r"\b(?:unreal engine|octane render|v-?ray)\b",
    re.IGNORECASE,
)


def strip_style_overrides(text: str) -> str:
    """The description with every clause that restyles the picture removed, the rest kept
    with its own punctuation. Clauses are sentences, and the parts between ';' and ','."""
    pieces = re.split(r"((?<=[.!?])\s+|\s*[;,]\s*)", str(text or ""))
    kept: list[str] = []
    separator = ""
    for position, piece in enumerate(pieces):
        if position % 2:
            separator = piece
            continue
        if not piece.strip() or _STYLE_OVERRIDE.search(piece):
            continue
        if kept:
            kept.append("; " if ";" in separator else ", " if "," in separator else " ")
        kept.append(piece.strip())
    return " ".join("".join(kept).split())


def _flatten(value: Any) -> str:
    """A structured answer said as one line: "key: value; key: value"."""
    if isinstance(value, dict):
        return "; ".join(
            f"{key}: {_flatten(item)}" for key, item in value.items() if _flatten(item)
        )
    if isinstance(value, list | tuple):
        return ", ".join(_flatten(item) for item in value if _flatten(item))
    return "" if value is None else str(value)


def _max_length(field: Any) -> int | None:
    for meta in getattr(field, "metadata", None) or []:
        limit = getattr(meta, "max_length", None)
        if isinstance(limit, int):
            return limit
    return None


def _coerce(data: dict[str, Any], model: type[BaseModel]) -> dict[str, Any]:
    """Fit a model's answer to the schema instead of refusing it for its shape.

    Kael's shot plan for the ATLAS film was 14,036 characters of camera, lens, light and
    composition — and all of it was thrown away because two `audio_intent` lines ran past 200
    characters, so the whole pack failed validation and every shot was rebuilt from the
    writer's one-line description. His visual bible went the same way for describing the
    palette, the light and the camera as objects instead of sentences. A field that is too
    long is shortened, a structured value is said as a sentence; nothing good is discarded
    for its formatting. A text that is too long is cut at a whole word, never mid-word.

    A visual bible's prompt-bound fields refuse codes in capitals and hex colours (the Nepal
    bible, 2026-09-26, was "NEPAL_CLIMATE_CRISIS" and "#2E4A66" throughout): a clause holding
    one is dropped, and a rule or exclusion holding one is dropped whole. Every hex colour
    found is kept in ``card_palette``, the one field only the local card compositor reads.
    """
    bible = model is VisualBible
    found_hex: list[str] = []
    fitted: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        if name not in data or (bible and name == "card_palette"):
            continue
        value = data[name]
        limit = _max_length(field)
        scrub = bible and name in PROMPT_BOUND_BIBLE_FIELDS
        if field.annotation is str:
            text = " ".join(_flatten(value).split())
            if scrub:
                found_hex.extend(_HEX_COLOUR.findall(text))
                text = _scrub_codes(text)
            fitted[name] = _fit(text, limit) if limit else text
        elif field.annotation == list[str]:
            items = value if isinstance(value, list) else [value]
            cleaned = [" ".join(_flatten(item).split()) for item in items]
            cleaned = [item for item in cleaned if item]
            if scrub:
                found_hex.extend(hexes for item in cleaned for hexes in _HEX_COLOUR.findall(item))
                cleaned = [
                    item
                    for item in cleaned
                    if not _HEX_COLOUR.search(item) and not lint.ENUM_CODE.search(item)
                ]
            fitted[name] = cleaned[:limit] if limit else cleaned
        else:
            fitted[name] = value
    if bible:
        given = data.get("card_palette")
        stated = given if isinstance(given, list) else [given] if given else []
        colours = [
            _hex6(str(item).strip())
            for item in [*stated, *found_hex]
            if _HEX_COLOUR.fullmatch(str(item).strip())
        ]
        palette = list(dict.fromkeys(colours))[:16]
        if palette:
            fitted["card_palette"] = palette
    return fitted


def _first_object(text: str, wanted: tuple[str, ...]) -> dict[str, Any] | None:
    """The first JSON object in a model's answer that carries one of the fields asked for."""
    raw = (text or "").strip()
    decoder = json.JSONDecoder()
    start = raw.find("{")
    tried = 0
    while start >= 0 and tried < 400:
        tried += 1
        try:
            data, _end = decoder.raw_decode(raw, start)
        except ValueError:
            start = raw.find("{", start + 1)
            continue
        if isinstance(data, dict) and any(key in data for key in wanted):
            return data
        start = raw.find("{", start + 1)
    return None


@dataclass
class ShotPlanParse:
    """What could be read of a shot plan, how, and what the decoder said about the rest.

    ``method`` is ``strict`` (the answer decoded as written), ``repaired`` (it decoded after
    the narrow repair), ``salvaged`` (only shot by shot) or ``none``. ``error`` is the strict
    decoder's own message with its offset in the answer, kept even when a repair succeeded:
    it is what a re-ask tells the model, and what the Owner's event carries.
    """

    shots: dict[int, ShotPrompt] = dataclass_field(default_factory=dict)
    method: str = "none"
    error: str | None = None


def repair_json(text: str) -> str:
    """The narrow repair, and nothing else: an inner quote is escaped, a trailing comma dropped.

    Inside a string, a double quote that is not followed (after blanks) by one of ``, : } ]``
    or the end cannot be the string's end, so it is written as ``\\"``. Outside a string, a
    comma followed only by blanks and a closing bracket is removed. Valid JSON is unchanged.
    The Nepal plan (2026-09-26) was lost to exactly the first case:
    ``"Subtle metallic "ping" as bars stop, then silence"``.
    """
    out: list[str] = []
    in_string = False
    index = 0
    size = len(text)
    while index < size:
        char = text[index]
        if in_string:
            if char == "\\":
                out.append(text[index : index + 2])
                index += 2
                continue
            if char == '"':
                ahead = index + 1
                while ahead < size and text[ahead] in " \t\r\n":
                    ahead += 1
                if ahead >= size or text[ahead] in ",:}]":
                    in_string = False
                    out.append(char)
                else:
                    out.append('\\"')
                index += 1
                continue
            out.append(char)
            index += 1
            continue
        if char == '"':
            in_string = True
        elif char == ",":
            ahead = index + 1
            while ahead < size and text[ahead] in " \t\r\n":
                ahead += 1
            if ahead < size and text[ahead] in "}]":
                index += 1
                continue
        out.append(char)
        index += 1
    return "".join(out)


def _decoder_error(raw: str, start: int, exc: json.JSONDecodeError) -> str:
    """The decoder's message, placed in the model's own answer (offset, line, column)."""
    offset = start + exc.pos
    line = raw.count("\n", 0, offset) + 1
    column = offset - (raw.rfind("\n", 0, offset) + 1) + 1
    return f"{exc.msg} at offset {offset} (line {line}, column {column})"


def _shots_from(items: Any) -> dict[int, ShotPrompt]:
    """Every shot that can be placed, fitted to the schema; a broken shot costs only itself."""
    from pydantic import ValidationError  # noqa: PLC0415

    shots: dict[int, ShotPrompt] = {}
    for raw in items if isinstance(items, list) else []:
        if not isinstance(raw, dict):
            continue
        try:
            shot = ShotPrompt.model_validate(_coerce(raw, ShotPrompt))
        except ValidationError:
            continue
        shots.setdefault(shot.scene_index, shot)
    return shots


def _salvage_shots(raw: str) -> list[dict[str, Any]]:
    """Each shot decoded on its own, from the answer as written or after the narrow repair.

    A shot starts at the brace before its ``"scene_index"`` and ends where the next shot
    starts; one shot that cannot be read no longer takes the others with it, and a repair
    that misreads one shot's quotes cannot spill into the next.
    """
    decoder = json.JSONDecoder()
    starts: list[int] = []
    for match in re.finditer(r'"scene_index"\s*:', raw):
        brace = raw.rfind("{", 0, match.start())
        if brace >= 0 and brace not in starts:
            starts.append(brace)
    found: list[dict[str, Any]] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(raw)
        chunk = raw[start:end]
        for attempt in (chunk, repair_json(chunk)):
            try:
                data, _end = decoder.raw_decode(attempt)
            except ValueError:
                continue
            if isinstance(data, dict) and "scene_index" in data and "shots" not in data:
                found.append(data)
                break
    return found


def parse_shot_plan(text: str) -> ShotPlanParse:
    """A model's shot plan read in four steps, each only when the one before failed.

    A strict parse; the narrow repair (`repair_json`); a salvage shot by shot; and otherwise
    nothing, with the decoder's error kept for the one re-ask. Never raises.
    """
    raw = str(text or "")
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return ShotPlanParse(error="no JSON object in the answer")
    candidate = raw[start : end + 1]
    error: str | None = None
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        error = _decoder_error(raw, start, exc)
        data = _first_object(raw, ("shots",))
        if data is not None:
            # A strict object that stands on its own, with prose or a second object around it.
            error = None
    if isinstance(data, dict) and "shots" in data:
        return ShotPlanParse(_shots_from(data.get("shots")), "strict", error)
    try:
        repaired = json.loads(repair_json(candidate))
    except json.JSONDecodeError:
        repaired = None
    if isinstance(repaired, dict) and "shots" in repaired:
        return ShotPlanParse(_shots_from(repaired.get("shots")), "repaired", error)
    salvaged = _shots_from(_salvage_shots(raw))
    if salvaged:
        return ShotPlanParse(salvaged, "salvaged", error)
    return ShotPlanParse({}, "none", error or "no shot plan in the answer")


def _parse_shot_pack(text: str) -> ShotPack | None:
    """Every shot that can be placed, as a pack; None when not one shot could be read."""
    parsed = parse_shot_plan(text)
    shots = [parsed.shots[index] for index in parsed.shots][:60]
    return ShotPack(shots=shots) if shots else None


# ------------------------------------------------------------------ whole-item payloads


def _scene_lists(data: Any) -> list[list[Any]]:
    """Every ``scenes`` list inside a payload, at whatever depth the payload keeps it."""
    found: list[list[Any]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "scenes" and isinstance(value, list):
                found.append(value)
            else:
                found.extend(_scene_lists(value))
    return found


def _dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def trim_payload(data: dict[str, Any], limit: int) -> tuple[dict[str, Any], dict[str, int]]:
    """The payload made to fit ``limit`` characters by dropping whole items, never by slicing.

    First the longest claims, one at a time; then the studio's prompt lessons, last first;
    then whole scenes from the end. What is sent always parses, and whatever is sent is
    whole: the payload used to be cut at 12,000 / 16,000 characters, mid-string, and the
    model was handed JSON that did not close. Returns the fitted copy and what was dropped.
    """
    fitted: dict[str, Any] = json.loads(_dumps(data))
    dropped = {"claims": 0, "lessons": 0, "scenes": 0}
    while len(_dumps(fitted)) > limit:
        holders = [
            scene
            for scenes in _scene_lists(fitted)
            for scene in scenes
            if isinstance(scene, dict) and isinstance(scene.get("claims"), list) and scene["claims"]
        ]
        if holders:
            longest = max(
                (
                    (scene, position)
                    for scene in holders
                    for position in range(len(scene["claims"]))
                ),
                key=lambda pair: len(_dumps(pair[0]["claims"][pair[1]])),
            )
            del longest[0]["claims"][longest[1]]
            dropped["claims"] += 1
            continue
        lessons = fitted.get("lessons")
        if isinstance(lessons, list) and lessons:
            lessons.pop()
            dropped["lessons"] += 1
            continue
        lists = [scenes for scenes in _scene_lists(fitted) if scenes]
        if not lists:
            break
        lists[0].pop()
        dropped["scenes"] += 1
    return fitted, dropped


def _parse_bible(text: str) -> VisualBible | None:
    from pydantic import ValidationError  # noqa: PLC0415

    data = _first_object(text, tuple(VisualBible.model_fields))
    if data is None:
        return None
    try:
        return VisualBible.model_validate(_coerce(data, VisualBible))
    except ValidationError:
        return None


# ------------------------------------------------------------------ the bible


def build_visual_bible(
    engine: Engine,
    registry: Any,
    storyboard_id: str,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Decide the one look this film has, and keep it on the storyboard.

    Falls back to a bible composed from the film's own fields when no model can be reached:
    a studio without a language model still produces one consistent-looking film rather than
    a set of unrelated shots.
    """
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise PromptError(f"Storyboard {storyboard_id} not found")
        facts = _film_facts(session, board)
        editor = agent_for_role(session, PROMPT_ROLE)
        editor_id = editor.id if editor else None

    bible: VisualBible | None = None
    run_id = None
    if editor_id is not None and registry is not None:
        fitted, _dropped = trim_payload(facts, MAX_BIBLE_PAYLOAD_CHARS)
        payload = _dumps(fitted)
        result = _run(
            engine,
            registry,
            editor_id,
            "visual_bible",
            _BIBLE_INSTRUCTIONS + wrap_in_inert_boundary(payload, "approved-film"),
            BIBLE_TEMPLATE,
            correlation,
            f"Stabilesc privirea filmului «{facts['title'][:50]}».",
            2200,
        )
        if result is not None:
            run_id = result["id"]
            bible = _parse_bible(result.get("output_text") or "")

    record = (bible or VisualBible()).model_dump()
    record["avoid"] = _avoid_list(record.get("avoid"))
    record.setdefault("aspect_ratio", facts["aspect_ratio"])
    record["aspect_ratio"] = facts["aspect_ratio"]
    record["quality_target"] = "premium cinematic, readable on a phone in vertical framing"
    if not record.get("style"):
        record["style"] = f"{facts['visual_style'].replace('_', ' ').lower()}, cinematic"
    if not record.get("continuity_rules"):
        record["continuity_rules"] = [
            "the same palette, light and time of day across every shot unless the story says "
            "otherwise",
            "a character's face, hair and clothing are identical from shot to shot",
            "the location holds unless a scene explicitly moves",
        ]
    record["source"] = "director" if bible is not None else "studio defaults"
    record["written_at"] = utc_now()

    with Session(engine) as session, session.begin():
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise PromptError(f"Storyboard {storyboard_id} not found")
        board.visual_bible_json = record
        append_event(
            session,
            "media.visual_bible_written",
            "storyboard",
            storyboard_id,
            1,
            {"source": record["source"], "rules": len(record["continuity_rules"])},
            correlation,
        )
    return {"storyboard_id": storyboard_id, "bible": record, "run_id": run_id}


def _avoid_list(raw: Any) -> list[str]:
    """The film's own exclusions, on top of the ones the studio always refuses."""
    theirs = [_fit(str(item), 120) for item in raw] if isinstance(raw, list) else []
    merged = list(DEFAULT_NEGATIVES)
    for item in theirs:
        if item and item.lower() not in {m.lower() for m in merged}:
            merged.append(item)
    return merged[:16]


# ------------------------------------------------------------------ the shots


def write_shot_prompts(
    engine: Engine,
    registry: Any,
    storyboard_id: str,
    correlation_id: str | None = None,
    *,
    repair_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write the full prompt package for every shot of an approved film.

    The package is identical in both environments: the environment decides which model is
    bought, never how well the shot is described. `visual_prompt` is rewritten from the
    package, so the render, the costing and quality control need to know nothing about this.
    """
    from app.factual.story_review import story_gate  # noqa: PLC0415
    from app.media.shooting_sheet import film_is_closed  # noqa: PLC0415 - it imports us

    correlation = correlation_id or str(uuid4())
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise PromptError(f"Storyboard {storyboard_id} not found")
        if film_is_closed(session, storyboard_id):
            # «Închide filmul»: a closed film is not described again, and no model is run for it.
            raise PromptError(FILM_CLOSED_PROMPTS_RO)
        # Describing the shots is the last step before money, so it is where the story gate
        # is enforced: a film whose story nobody judged does not get described, and one the
        # review sent back waits for the rewrite.
        passed, why = story_gate(session, board.script_draft_id)
        if not passed:
            raise PromptError(why)
        need_bible = not board.visual_bible_json or (
            registry is not None and board.visual_bible_json.get("source") == "studio defaults"
        )
        facts = _film_facts(session, board)
        editor = agent_for_role(session, PROMPT_ROLE)
        editor_id = editor.id if editor else None
        lessons = prompt_lessons(session)
    serial = bool(facts.get("serial"))
    # An episode of the serial does not decide a look: it has the series' one, read from the
    # Owner's proposal and written onto the storyboard every time, never asked of a model.
    look = load_series_look() if serial else {}
    if serial:
        with Session(engine) as session, session.begin():
            board = session.get(Storyboard, storyboard_id)
            if board is not None:
                board.visual_bible_json = series_bible(look, board.aspect_ratio)
    elif need_bible:
        build_visual_bible(engine, registry, storyboard_id, correlation)
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        bible = dict((board.visual_bible_json or {}) if board else {})

    expected = [int(scene["scene_index"]) for scene in facts["scenes"]]
    packs: dict[int, ShotPrompt] = {}
    run_id = None
    run_ids: list[str] = []
    # Whether a model answered at all: an answer that cannot be read is a lost plan, never a
    # reason to fall back to templates in silence (the Nepal film, 2026-09-26).
    answered = False
    reasked = False
    parsed = ShotPlanParse()
    if editor_id is not None and registry is not None:
        if serial:
            data: dict[str, Any] = {
                "series_look": {
                    "style_block": look.get("block") or "",
                    "version": look.get("version"),
                    "continuity_rules": look.get("continuity_rules") or [],
                },
                "episode": facts,
                "lessons": lessons,
            }
            instructions, template = _SERIAL_SHOTS_INSTRUCTIONS, SERIAL_SHOTS_TEMPLATE
        else:
            data = {"visual_bible": bible, "film": facts, "lessons": lessons}
            instructions, template = _SHOTS_INSTRUCTIONS, SHOTS_TEMPLATE
        if repair_context:
            data["repair_context"] = repair_context
        fitted, _dropped = trim_payload(data, MAX_SHOTS_PAYLOAD_CHARS)
        prompt = instructions + wrap_in_inert_boundary(_dumps(fitted), "approved-film")
        result = _run(
            engine,
            registry,
            editor_id,
            "shot_prompts",
            prompt,
            template,
            correlation,
            f"Scriu prompturile pentru {len(facts['scenes'])} cadre.",
            7000,
        )
        if result is not None:
            answered = True
            run_id = result["id"]
            run_ids.append(str(run_id))
            parsed = parse_shot_plan(result.get("output_text") or "")
            packs = dict(parsed.shots)
            missing = [index for index in expected if index not in packs]
            # ONE re-ask, carrying the decoder's own words, for a factual film. The serial's
            # shots are composed from its fixed look when the model's are missing (S8).
            if missing and not serial:
                reasked = True
                again = _run(
                    engine,
                    registry,
                    editor_id,
                    "shot_prompts",
                    prompt + _reask_note(parsed, missing),
                    template,
                    correlation,
                    f"Cer din nou planul de cadre: lipsesc cadrele {_listed(missing)}.",
                    7000,
                )
                if again is not None:
                    run_id = again["id"]
                    run_ids.append(str(run_id))
                    second = parse_shot_plan(again.get("output_text") or "")
                    for index, answer in second.shots.items():
                        packs.setdefault(index, answer)
                    parsed = ShotPlanParse(packs, second.method, second.error)

    allowed = _allowed_text(facts)
    written: list[dict[str, Any]] = []
    refused: list[str] = []
    previous_ending = ""
    kept_from_before: list[int] = []
    moves: list[str] = []
    with Session(engine) as session, session.begin():
        # Behind the write lock the Owner's close takes: a film closed while the model wrote is
        # left as it is (REJECTED, its scenes untouched). Setting it NEEDS_SHOT_PLAN or APPROVED
        # here would reopen it, and its topic would hold the studio again.
        lock_for_write(session)
        if film_is_closed(session, storyboard_id):
            raise PromptError(FILM_CLOSED_PROMPTS_RO)
        scenes = list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == storyboard_id)
                .order_by(StoryboardScene.scene_index)
            )
        )
        facts_by_index = {int(s["scene_index"]): s for s in facts["scenes"]}
        lost = answered and not serial and any(s.scene_index not in packs for s in scenes)
        for scene in scenes:
            scene_facts = facts_by_index.get(scene.scene_index, {})
            shot = packs.get(scene.scene_index)
            earlier = dict(scene.prompt_json or {})
            if (lost or not answered) and shot is None and earlier.get("source") == SOURCE_MODEL:
                # A plan a model wrote before is never overwritten by a template because
                # this answer could not be read, nor because no model answered at all this
                # time (the day asks a NEEDS_SHOT_PLAN film again, and the run may be refused).
                kept_from_before.append(scene.scene_index)
                previous_ending = str(earlier.get("ending_frame") or "")
                continue
            package, notes = _validated_package(shot, scene_facts, bible, allowed, previous_ending)
            refused.extend(f"cadrul {scene.scene_index}: {note}" for note in notes)
            if serial:
                package = _serial_package(package, shot, scene_facts, look)
                scene.shot_type = SHOT_TYPES[package["shot_size"]]
                package["source"] = SOURCE_MODEL if shot is not None else SOURCE_SERIES_LOOK
                composed = compose_serial_prompt(package, look)
                # The shot's own movement, so the motion step has words of its own and the
                # film's camera varies: the plan's move, else one that suits the shot's size
                # and is not the scene before's, as the factual compile chooses. A serial
                # given «static» everywhere was BLOCKed SAME_CAMERA_EVERY_SCENE on every
                # rewrite (2026-10-11, f06808c9), whatever its writer wrote.
                move = _serial_camera_move(package, moves)
                moves.append(move)
                package["camera_move"] = move
                package["motion_prompt"] = compose_serial_motion(package, look)
                package["still_prompt"] = composed
            else:
                # Two prompts per filmed scene (compile_prompts); a scene composed locally
                # carries none, and its visual_prompt stays the writer's line.
                package["scene_kind"] = str(getattr(scene, "scene_kind", None) or LIVE_KIND).upper()
                package["shot_type"] = scene.shot_type
                compiled = compile_prompts(package, bible, previous_moves=moves)
                package.update(compiled)
                if compiled["camera_move"]:
                    moves.append(compiled["camera_move"])
                composed = compiled["still_prompt"] or str(
                    package.get("writer_visual") or scene.visual_prompt or ""
                )
            scene.prompt_json = package
            scene.story_purpose = package["story_purpose"]
            scene.visual_prompt = composed
            previous_ending = str(package.get("ending_frame") or "")
            written.append(
                {
                    "scene_index": scene.scene_index,
                    "story_purpose": package["story_purpose"],
                    "chars": len(composed),
                    "from_model": shot is not None,
                }
            )
        missing = [
            s.scene_index
            for s in scenes
            if s.scene_index not in packs and s.scene_index not in kept_from_before
        ]
        board = session.get(Storyboard, storyboard_id)
        if lost and missing:
            if board is not None:
                board.status = NEEDS_SHOT_PLAN
            append_event(
                session,
                "media.shot_prompts_incomplete",
                "storyboard",
                storyboard_id,
                1,
                {
                    "severity": "WARNING",
                    "from_model": sum(1 for item in written if item["from_model"]),
                    "missing_scenes": missing,
                    "kept_from_before": kept_from_before,
                    "decoder_error": parsed.error,
                    "parse_method": parsed.method,
                    "reasked": reasked,
                    "run_ids": run_ids,
                },
                correlation,
            )
        else:
            if board is not None and board.status == NEEDS_SHOT_PLAN:
                board.status = "APPROVED"  # the plan it was waiting for is written
            append_event(
                session,
                "media.shot_prompts_written",
                "storyboard",
                storyboard_id,
                1,
                {
                    "shots": len(written),
                    "from_model": sum(1 for item in written if item["from_model"]),
                    "repaired": refused[:6],
                    "parse_method": parsed.method,
                    "reasked": reasked,
                },
                correlation,
            )
    if lost and missing:
        logger.warning(
            "shot_prompts_incomplete",
            extra={"storyboard_id": storyboard_id, "missing": missing, "error": parsed.error},
        )
        raise ShotPlanUnusable(
            storyboard_id,
            missing,
            f"Planul de cadre al editorului nu a putut fi citit pentru cadrele "
            f"{_listed(missing)}, nici după a doua cerere; filmul așteaptă un plan "
            f"({NEEDS_SHOT_PLAN}).",
        )
    logger.info(
        "shot_prompts_written",
        extra={"storyboard_id": storyboard_id, "shots": len(written), "repaired": len(refused)},
    )
    return {
        "storyboard_id": storyboard_id,
        "shots": written,
        "repaired": refused,
        "run_id": run_id,
        "bible": bible,
    }


def _listed(indexes: list[int]) -> str:
    return ", ".join(str(index) for index in indexes)


def _reask_note(parsed: ShotPlanParse, missing: list[int]) -> str:
    """What the one re-ask adds to the brief: the decoder's error and the missing scenes."""
    return (
        "\n\nYour previous answer could not be read in full. The JSON decoder said: "
        f"{parsed.error or 'no readable shot plan'}. Scenes missing from what could be read: "
        f"{_listed(missing)}. Answer again with the complete JSON for every scene and nothing "
        'else. Inside a value, write a double quote as \\" or use single quotes.\n'
    )


def shot_plan_gaps(
    session: Session, storyboard_id: str, sources: Sequence[str] = (SOURCE_MODEL,)
) -> list[int]:
    """The scenes of a storyboard whose package came from none of ``sources``: the model's
    alone for a factual film, the series look's too for the office serial
    (`assembler.shot_plan_sources`; 2026-10-11, f06808c9: the sheet read every serial scene
    the look composed as a gap and refused the walk NEEDS_SHOT_PLAN, while the stills stage
    accepted them)."""
    return [
        scene.scene_index
        for scene in session.scalars(
            select(StoryboardScene)
            .where(StoryboardScene.storyboard_id == storyboard_id)
            .order_by(StoryboardScene.scene_index)
        )
        if (scene.prompt_json or {}).get("source") not in sources
    ]


def hold_for_shot_plan(engine: Engine, storyboard_id: str, correlation_id: str) -> list[int]:
    """Stop a film whose shots a model did not write: NEEDS_SHOT_PLAN and a WARNING event.

    Returns the scenes without a model package; an empty list means the film may go on and
    nothing was changed. Template prompts are a TEST convenience; in PRODUCTION the media
    stage asks this before anything is bought.

    A closed film (`shooting_sheet.film_is_closed`) is never held, which would reopen it: the
    answer is an empty list and nothing is changed; every buyer meets it closed at its lease.
    """
    from app.media.assembler import shot_plan_sources  # noqa: PLC0415 - it imports us
    from app.media.shooting_sheet import film_is_closed  # noqa: PLC0415 - it imports us

    # The serial's scenes composed from the series look are no gap (read before the lock).
    sources = shot_plan_sources(engine, storyboard_id)
    with Session(engine) as session, session.begin():
        # Behind the write lock the Owner's close takes, so a close is seen or comes after.
        lock_for_write(session)
        if film_is_closed(session, storyboard_id):
            return []
        gaps = shot_plan_gaps(session, storyboard_id, sources)
        board = session.get(Storyboard, storyboard_id)
        if not gaps or board is None:
            return gaps
        total = int(board.total_scenes or 0) or len(gaps)
        board.status = NEEDS_SHOT_PLAN
        append_event(
            session,
            "media.shot_prompts_incomplete",
            "storyboard",
            storyboard_id,
            1,
            {
                "severity": "WARNING",
                "from_model": max(0, total - len(gaps)),
                "missing_scenes": gaps,
                "decoder_error": None,
                "parse_method": "not_model",
                "reasked": False,
                "run_ids": [],
                "held_by": "media_stage",
            },
            correlation_id,
        )
    return gaps


def _validated_package(
    shot: ShotPrompt | None,
    scene: dict[str, Any],
    bible: dict[str, Any],
    allowed: str,
    previous_ending: str,
) -> tuple[dict[str, Any], list[str]]:
    """One shot's package, with every gap filled and every invented fact removed.

    A missing field is filled from what the film already states, because a shot with no
    lighting is a shot whose lighting the model invents. An invented number is cut: the
    picture would make it look documented.
    """
    notes: list[str] = []
    purpose = str((shot.story_purpose if shot else "") or scene.get("story_purpose") or "").upper()
    if purpose not in SCENE_PURPOSES:
        purpose = "DEVELOPMENT"
        notes.append("scopul cadrului lipsea")
    package: dict[str, Any] = {
        "story_purpose": purpose,
        "narration": str(scene.get("narration") or ""),
        # Kept so a rerun starts from the writer's line again, whatever this step composed.
        "writer_visual": str(scene.get("writer_visual") or ""),
        "seconds": float(scene.get("seconds") or 0),
        "subject": (shot.subject if shot else "") or str(scene.get("writer_visual") or ""),
        "action": (shot.action if shot else "") or str(scene.get("writer_visual") or ""),
        "environment": (shot.environment if shot else "") or str(bible.get("world") or ""),
        "camera": (shot.camera if shot else "")
        or f"{str(scene.get('shot_type') or 'MEDIUM').lower()} shot, locked camera",
        "lighting": (shot.lighting if shot else "") or str(bible.get("lighting") or ""),
        "composition": (shot.composition if shot else "")
        or "subject centred in a vertical frame, readable on a phone",
        # Two clauses, so the compiler reads the first as the subject's motion and the second
        # as the world's (`_motion_intent`); said without camera words, which it drops. Until
        # 2026-10-11: "slow, natural movement within the frame", every word of it dropped.
        "motion": (shot.motion if shot else "")
        or "the subject carries on with its action; shadows drift and the light shifts around it",
        "emotion": (shot.emotion if shot else ""),
        "background": (shot.background if shot else ""),
        "continuity": (shot.continuity if shot else "") or previous_ending,
        "ending_frame": (shot.ending_frame if shot else ""),
        "audio_intent": (shot.audio_intent if shot else "narration dominates"),
        "transition": (shot.transition if shot else "dissolve into the next shot"),
        "avoid": _avoid_list(shot.avoid if shot else None),
        "characters": scene.get("characters") or [],
        # The plan's own camera move, when it named one from the enum; the compiler
        # chooses one otherwise (`choose_camera_move`).
        "camera_move": (
            shot.camera_move.strip().lower()
            if shot and shot.camera_move.strip().lower() in lint.CAMERA_MOVES
            else ""
        ),
        # Where this package came from. A render in PRODUCTION requires "model": template
        # prompts are a TEST convenience (SHOT_PLAN_PARSE, 2026-09-27).
        "source": SOURCE_MODEL if shot is not None else SOURCE_TEMPLATE,
    }
    # Only when the editor gave a usable one: a package without it is the package it was,
    # and the sheet's hashes of every film planned before stay what they were.
    framing = _second_framing(shot.second_framing if shot else None)
    if framing is not None:
        package["second_framing"] = framing
    for key in ("subject", "action", "environment", "background", "composition", "ending_frame"):
        original = str(package.get(key) or "")
        cleaned = strip_on_screen_text(original)
        if cleaned != " ".join(original.split()):
            package[key] = cleaned
            if "cerere de text în imagine scoasă" not in notes:
                notes.append("cerere de text în imagine scoasă")
    writer_line = strip_on_screen_text(str(scene.get("writer_visual") or ""))
    for field in REQUIRED_SHOT_FIELDS:
        if not str(package.get(field) or "").strip():
            package[field] = writer_line or str(bible.get("style") or "")
            notes.append(f"{field} lipsea")
    invented = new_numbers(
        " ".join(str(package[k]) for k in ("subject", "action", "environment", "background")),
        allowed,
    )
    if invented:
        notes.append("cifre inventate scoase: " + ", ".join(invented[:4]))
        for key in ("subject", "action", "environment", "background"):
            text = str(package[key])
            for value in invented:
                text = re.sub(rf"\b{re.escape(value)}\b", "", text)
            package[key] = " ".join(text.split())
    return package, notes


def _second_framing(raw: Any) -> dict[str, Any] | None:
    """The editor's second framing as the edit reads it: a subject (cleaned of on-screen
    text) and a centre held inside the frame; None for anything that is not one."""
    if not isinstance(raw, dict):
        return None
    centre: list[float] = []
    for key in ("centre_x", "centre_y"):
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        centre.append(round(min(1.0, max(0.0, float(value))), 3))
    subject = strip_on_screen_text(" ".join(str(raw.get("subject") or "").split()))[:200]
    return {"subject": subject, "centre_x": centre[0], "centre_y": centre[1]}


def _short_name(name: Any) -> str:
    """How a shot names a character: "Sarah Executive" -> "Sarah", "Dr. Aris ..." -> "Dr. Aris"."""
    words = str(name or "").split()
    if not words:
        return ""
    if words[0].rstrip(".").lower() in ("dr", "mr", "mrs", "ms", "prof") and len(words) > 1:
        return f"{words[0]} {words[1]}"
    return words[0]


def _fit(text: str, limit: int) -> str:
    """``text`` cut at a word boundary to at most ``limit`` characters."""
    said = " ".join(str(text or "").split())
    if len(said) <= limit:
        return said
    cut = said[: max(0, limit)].rsplit(" ", 1)[0]
    return cut.rstrip(",;: ")


def _clauses(text: Any, separators: str) -> list[str]:
    said = " ".join(str(text or "").split()).rstrip(". ")
    return [part.strip() for part in re.split(f"[{separators}]", said) if part.strip()]


def _identity(character: dict[str, Any], limit: int) -> str:
    """A character as their bible describes them, in at most ``limit`` characters.

    Whole clauses, most telling first: the hair, then the first garment, then the rest of the
    face and of the outfit while they fit. Cut mid-phrase, "a navy executive blazer" became
    "a navy executive", a garment the bible never named.
    """
    face = _clauses(character.get("face_hair"), ";")
    outfit = _clauses(character.get("outfit"), ",;")
    if outfit:
        outfit[0] = f"wearing {outfit[0][:1].lower()}{outfit[0][1:]}"
    name = f"{_short_name(character.get('name'))}: "
    kept = set(face[:1] + outfit[:1])
    size = len(name) + sum(len(part) + 2 for part in kept)
    for extra in face[1:] + outfit[1:]:
        if size + len(extra) + 2 > limit:
            break
        kept.add(extra)
        size += len(extra) + 2
    # Said in the bible's order: the whole face, then the clothes. A clause that does not
    # fit whole is left out, never cut in the middle: «Tousled wavy dark hair, wearing;» and
    # «Brunette professional bob with.» were what the first episode's stills said of their
    # people (2026-10-11, f06808c9).
    parts = [part for part in face + outfit if part in kept]
    text = name + ", ".join(parts)
    while len(text) > limit and len(parts) > 1:
        parts.pop()
        text = name + ", ".join(parts)
    return _clean_cut(_fit(text, limit))


def _serial_package(
    package: dict[str, Any],
    shot: ShotPrompt | None,
    scene: dict[str, Any],
    look: dict[str, Any],
) -> dict[str, Any]:
    """A serial shot's package: the beat's room, the people in frame and the camera.

    The room is the beat's, never the model's; the people are the beat's speakers first, as
    their bibles describe them; the camera is the model's, or the size the beat's part asks
    for. Without a model the action is the beat's scene line with each speaker's direction,
    and what they say is left to the voice: a line in a picture prompt is drawn as writing.
    """
    cast = [c for c in scene.get("characters") or [] if isinstance(c, dict)]
    by_id = {c.get("id"): c for c in cast}
    speakers = [by_id[cid] for cid in scene.get("speaker_ids") or [] if cid in by_id]
    if not speakers:
        speakers = cast[:2]
    size = serial_shot_size(scene.get("part"), int(scene.get("scene_index") or 1), len(speakers))
    if size == "establishing":
        in_frame = speakers or cast
    elif size == "two_shot":
        in_frame = speakers[:2]
    else:
        in_frame = speakers[:1]
    # The people of the beat who do not speak stand at their own desks; a speaker outside a
    # single's frame is off camera, not in the background.
    others = [
        _short_name(c.get("name"))
        for c in cast
        if c not in in_frame and c not in speakers and c.get("name")
    ]
    others += [_short_name(name) for name in scene.get("background") or [] if name]
    focus = _short_name(in_frame[0].get("name")) if in_frame else "the speaker"
    sizes = look.get("shot_sizes") or {}
    default_camera = str(sizes.get(size) or "").replace("{name}", focus)

    said: list[str] = []
    feelings: list[str] = []
    previous = None
    for line in scene.get("lines") or []:
        who = _short_name(line.get("speaker"))
        if not who or who == previous:
            continue
        direction = strip_on_screen_text(str(line.get("direction") or ""))
        verb = "speaks" if previous is None else "answers"
        said.append(f"{who}, {direction}, {verb}" if direction else f"{who} {verb}")
        if direction:
            feelings.append(f"{who} {direction}")
        previous = who
    writer_line = strip_on_screen_text(str(scene.get("writer_visual") or ""))
    spoken = "; ".join(said) + "." if said else ""
    fallback_action = " ".join(part for part in (writer_line, spoken) if part)

    # While the series has a look, a model may describe the shot but never restyle it: what
    # it wrote that asks for another medium or frame is taken out (`strip_style_overrides`).
    restyle = strip_style_overrides if look.get("in_use") else (lambda text: text)
    package = dict(package)
    model_action = restyle(str(package.get("action") or "")) if shot and shot.action else ""
    package["action"] = model_action or fallback_action
    package["emotion"] = (restyle(shot.emotion) if shot and shot.emotion else "") or "; ".join(
        feelings
    )
    model_camera = restyle(strip_on_screen_text(shot.camera)) if shot and shot.camera else ""
    package["camera"] = model_camera or default_camera
    background = restyle(str(package.get("background") or "")) if shot and shot.background else ""
    if not background and others:
        background = "at their own desks behind them: " + ", ".join(dict.fromkeys(others))
    package["background"] = background
    package["location"] = str(scene.get("location") or "")
    package["shot_size"] = size
    package["in_frame"] = in_frame
    if look.get("in_use"):
        package["lighting"] = "the series look"
    package["avoid"] = list(look.get("avoid") or []) or package.get("avoid") or []
    package["series_look_version"] = look.get("version") if look.get("in_use") else None
    package["from_model"] = shot is not None
    purpose = PART_PURPOSES.get(str(scene.get("part") or "").lower())
    if purpose and not (shot and shot.story_purpose):
        package["story_purpose"] = purpose
    return package


#: How a serial still fills the tall frame: one picture, the people high in it. The first
#: episode's stills of scenes 3, 4 and 7 (2026-10-11, f06808c9) came back as the same picture
#: three times, stacked, on both candidates: their prompts described a camera path over time
#: and a chain of moments, and said nothing of the frame; scenes 1 and 2, one moment each,
#: were fine. The factual compile says the same of its frame (COMPOSITION_SENTENCE).
SERIAL_FRAME_SENTENCE = (
    "One continuous picture fills the whole tall frame, the people in its upper two thirds."
)
#: The paper and the glass in a serial still carry no writing: the look forbids written words,
#: and the vision gate still read lettering and number grids on a ledger drawn for «pauses
#: before the number» (2026-10-12, 08:03, scene 4 of f06808c9, twice). Said without the
#: words the prompt check reads as a request for text («lettering», «digits»).
SERIAL_BLANK_SENTENCE = "Pages and screens are blank."
_WRITING_SURFACES = re.compile(
    r"\b(?:ledger|page|pages|paper|papers|note|notes|notebook|notepad|book|books|screen"
    r"|screens|monitor|monitors|laptop|phone|tablet|whiteboard|board|sign|poster|label"
    r"|document|documents|form|forms|invoice|invoices|report|reports|letter|letters)\b",
    re.IGNORECASE,
)
#: A function word left hanging at the end of a cut phrase ("wearing", "with", "in a").
_DANGLING_TAIL = re.compile(
    r"(?:\s+\b(?:wearing|with|in|a|an|the|and|or|but|over|of|on|at|to|for|under|as|his|her"
    r"|their|its)\b)+$",
    re.IGNORECASE,
)


def _clean_cut(text: str) -> str:
    """A cut phrase without a function word hanging at its end."""
    return _DANGLING_TAIL.sub("", text.rstrip(" ,;:-")).rstrip(" ,;:-")


def _still_moment(action: str) -> str:
    """The first moment of a serial beat's action, for its still: each person's clause up to
    its first later moment («then», «finally», «eventually», «next,») and up to its first
    comma, a clause that opens with a later moment left out. An image model draws a chain of
    moments as stacked panels (2026-10-11, f06808c9), and a chain joined by commas alone
    («opens both hands as if starting a pitch, the gesture stalls halfway and dies, he
    restarts his sentence») is still a chain (2026-10-12, 08:01, scene 3 twice more); the
    whole chain is the motion prompt's (`compose_serial_motion`)."""
    kept: list[str] = []
    for clause in re.split(r";\s*", " ".join(str(action or "").split()).rstrip(". ")):
        part = clause.strip()
        if not part or lint.SEQUENCE_OPENER.match(part):
            continue
        marks = [
            found.start()
            for found in (lint.STILL_THEN.search(part), lint.LATER_MOMENT.search(part))
            if found
        ]
        if marks:
            part = _then_head(part, min(marks))
        part = _clean_cut(_first_moment(part))
        if part:
            kept.append(part)
    return "; ".join(kept)


#: After a comma, a new moment: a pronoun or «then» opening it, or a verb of motion in its
#: first three words («pauses before», «the gesture stalls», «restarts his») — never a tail
#: that only describes the same moment («arms crossed», «eyes on the street», «hands on
#: hips», «a brass pen in hand»), which stays.
_MOMENT_OPENER = re.compile(r"^(?:he|she|they|it|we|then|now|next|and then)\b", re.IGNORECASE)
_MOMENT_VERB = re.compile(
    r"\b(?:pauses?|stalls?|dies|restarts?|holds?|lets?|waits?|stops?|starts?|begins?|ends?"
    r"|goes|comes?|says?|answers?|replies|shrugs?|sighs?|freezes?|grins?|frowns?|blinks?"
    r"|swallows?|exhales?|inhales?|straightens?|settles?|folds?|slides?|flips?|picks?|sets?"
    r"|places?|puts?|checks?|reads?|clicks?|scrolls?|stares?|squints?|tilts?|hovers?|rests?"
    r"|lands?|falls?|collapses?|spreads?|counts?|lists?|mouths?|murmurs?|snaps?|slams?|sips?"
    r"|drinks?|eats?|bites?|chews?|glares?|peers?|flinches|winces?|clears|closes?|opens?"
    r"|lowers?|raises?|drops?|lifts?|turns?|looks?|leans?|nods?|shakes?|taps?|points?)\b",
    re.IGNORECASE,
)


def _next_moment(tail: str) -> bool:
    words = tail.split()
    if not words:
        return False
    if _MOMENT_OPENER.match(tail):
        return True
    if words[0].lower().endswith("ing"):
        # A participle after the name's comma («Kael, leaning back, arms crossed») describes
        # this moment; a new one has its own finite verb.
        return False
    head = " ".join(words[:3])
    return bool(_MOMENT_VERB.search(head) or lint.SUBJECT_MOTION.search(head))


def _first_moment(clause: str) -> str:
    """One person's clause up to the comma that begins its next moment; the descriptive
    tails of the same moment («leaning back, arms crossed») stay."""
    head, sep, rest = clause.partition(",")
    while sep:
        if _next_moment(rest.strip()):
            break
        more, sep, rest = rest.partition(",")
        head = f"{head},{more}"
    return head.strip()


def _serial_framing(package: dict[str, Any], look: dict[str, Any], focus: str) -> str:
    """The still's camera: the look's fixed framing for the shot's size, the focus named;
    without a look, the first clause of the plan's camera (its framing, before its path)."""
    sizes = look.get("shot_sizes") or {}
    framing = str(sizes.get(str(package.get("shot_size") or "")) or "").replace("{name}", focus)
    framing = " ".join(framing.split()).rstrip(". ")
    if framing:
        return framing
    camera = " ".join(str(package.get("camera") or "").split())
    return _clean_cut(re.split(r"[,;:]", camera, maxsplit=1)[0]) if camera else ""


def compose_serial_prompt(package: dict[str, Any], look: dict[str, Any]) -> str:
    """The text the model receives for a serial shot, the series' look first, word for word.

    Then the room, the fixed framing for the shot's size, how one picture fills the tall
    frame, the people in frame (each as their bible describes them) and the first moment of
    the action; then, while there is room, the expression, the background and the continuity.
    The people are given less of their description, and then the action less of its words,
    until the prompt fits the look's cap: the look, the room and the frame never shrink.

    2026-10-11 (f06808c9): the stills of scenes 3, 4 and 7 came back as the same picture
    three times, stacked, on both candidates. Their prompts carried the plan's camera as a
    path over time («a slow tilt down from her face to the ledger and back up») and the
    action as a chain («taps …, pauses …, then lays the pen flat»): an image model draws a
    chain as panels. The path's move and the whole chain are the motion prompt's.
    """
    cap = int(look.get("max_prompt_chars") or 900)
    people = [c for c in package.get("in_frame") or [] if isinstance(c, dict)]
    focus = _short_name(people[0].get("name")) if people else "the speaker"
    framing = _serial_framing(package, look, focus)
    # Said in sentences, never under a template label: «Camera:» and «Action:» were the
    # rubrics the first episode's stills carried (2026-10-11, f06808c9), the prompt check
    # refused them (TEMPLATE_LABEL) on every rewrite, and the Director and the Video Editor
    # went round in circles while the storyboard waited.
    action = _still_moment(str(package.get("action") or ""))
    surfaces = " ".join(
        str(package.get(key) or "") for key in ("action", "location", "background", "subject")
    )
    head = [
        str(look.get("block") or "").strip(),
        f"Location: {package['location']}." if package.get("location") else "",
        _sentence(framing) if framing else "",
        SERIAL_FRAME_SENTENCE,
        # Only where there is paper or glass to write on: the sentence costs the people
        # their description under the cap, and a room without a page needs no blank one.
        SERIAL_BLANK_SENTENCE if _WRITING_SURFACES.search(surfaces) else "",
    ]
    if action and not action.endswith("."):
        action += "."

    def build(per_person: int, action_text: str) -> str:
        who = "; ".join(_identity(c, per_person) for c in people)
        parts = [
            *head,
            f"In frame, facing the viewer: {who}." if who else "",
            _sentence(action_text) if action_text else "",
        ]
        return " ".join(part for part in parts if part)

    per = 220 if len(people) <= 1 else 130 if len(people) == 2 else 90
    text = build(per, action)
    while len(text) > cap and per > 45:
        per -= 10
        text = build(per, action)
    if len(text) > cap and action:
        room = len(action) - (len(text) - cap)
        text = build(per, _clean_cut(_fit(action, room - 1)) + "." if room > 20 else "")
    text = _clean_cut(_fit(text, cap))
    # The exclusions are the look's own words already ("No written words ..."); a list of
    # them under «Avoid:» is read literally by an image model and is never said here.
    for prefix, value in (
        ("", package.get("emotion")),
        ("Behind them, ", package.get("background")),
        ("As in the shot before: ", package.get("continuity")),
    ):
        said = " ".join(str(value or "").split()).rstrip(". ")
        if not said:
            continue
        if prefix and said[:1].isupper() and not said.startswith(("AMN", "I ")):
            said = said[:1].lower() + said[1:]
        candidate = f"{text} {_sentence(prefix + said)}"
        if len(candidate) <= cap:
            text = candidate
    return text


#: The move table's size for each size of the series look's shot sizes (`serial_shot_size`).
_SERIAL_MOVE_SIZES: dict[str, str] = {
    "establishing": "wide",
    "two_shot": "medium",
    "single": "medium",
    "close": "close",
}


def _serial_camera_move(package: dict[str, Any], previous: list[str]) -> str:
    """One serial shot's camera move: the plan's own (`choose_camera_move`), unless it is the
    move of the scene before, when the shot's size chooses another, so a writer who names
    one move for every beat does not make a film of one movement (SAME_CAMERA_EVERY_SCENE)."""
    size = _SERIAL_MOVE_SIZES.get(str(package.get("shot_size") or ""), "medium")
    move = choose_camera_move(package, size, previous)
    if previous and move == previous[-1]:
        move = choose_camera_move({**package, "camera": "", "camera_move": ""}, size, previous)
    return move


#: What keeps the serial's people themselves while they move (2026-10-11, 45dc313).
SERIAL_FACES_SENTENCE = "Their faces stay expressive and the same people throughout."
#: The life of a serial shot beyond its lines: the people's bodies move as they speak, and
#: the room — the office picture's lamps and plants, in every room of the studio's house —
#: moves with them («Mișcare v2», 2026-10-11: the first board's clips held their people
#: still while they spoke).
SERIAL_LIFE_SENTENCE = (
    "As they speak their hands gesture, heads turn and shoulders shift, and behind them the "
    "lamp light flickers softly and the plants stir."
)


def compose_serial_motion(package: dict[str, Any], look: dict[str, Any]) -> str:
    """The movement of a serial shot: the shot's own camera move (``camera_move``, a held
    camera when none) with its path and tempo, the beat's whole action as movement (its
    chain of moments included: a still is one moment, a clip is the chain), the people's
    faces kept, the life of their bodies and of the room, the feeling, a second beat of
    camera on a beat of TWO_BEAT_SECONDS or more, and the closing every motion prompt
    carries.

    Until 2026-10-11 a serial scene had no motion prompt at all: the motion step sent the
    still's words again (`assembler._motion_prompt`), look block, room and rubrics included.
    """
    del look  # the look is in the picture; the movement is the beat's
    action = _sentence(" ".join(str(package.get("action") or "").split()))
    feeling = " ".join(str(package.get("emotion") or "").split()).rstrip(". ")
    move = str(package.get("camera_move") or "static")
    two_beats = move != "static" and _seconds_of(package) >= TWO_BEAT_SECONDS
    items = [
        (0, 0, MOVE_SENTENCES.get(move, MOVE_SENTENCES["static"])),
        (1, 1, action),
        (2, 2, SERIAL_FACES_SENTENCE),
        (3, 3, SERIAL_LIFE_SENTENCE),
        (5, 4, _sentence(feeling) if feeling else ""),
        (4, 5, END_BEAT if two_beats else ""),
        (0, 9, lint.MOTION_CLOSING),
    ]
    prompt = _fit_sentences(items, lint.DEFAULT_PROMPT_MAX_UTF16, MOTION_MAX_WORDS)
    if len(prompt.split()) < MOTION_MIN_WORDS:
        prompt = _fit_sentences(
            [*items, (6, 6, MOTION_PAD)], lint.DEFAULT_PROMPT_MAX_UTF16, MOTION_MAX_WORDS
        )
    return prompt


def compose_prompt(package: dict[str, Any], bible: dict[str, Any]) -> str:
    """The text the video model actually receives, in the order a model reads best.

    Subject and action first, because that is the shot; then the world, the camera, the light;
    then what must match the shot before it; and the exclusions last. Trimmed to a length
    that keeps the important half readable — a thousand meaningless words teach nothing.
    """
    # Each value is said once. When the shot plan was missing, the writer's single line filled
    # the subject, the action, the environment and the lighting, and the model received the
    # same sentence four times with nothing about light or place in it.
    seen: set[str] = set()

    def once(value: Any) -> str:
        said = " ".join(str(value or "").split()).rstrip(". ")
        if not said or said.casefold() in seen:
            return ""
        seen.add(said.casefold())
        return said

    characters = package.get("characters") or []
    who = "; ".join(
        f"{c.get('name')}: {c.get('face_hair')}, wearing {c.get('outfit')}"
        for c in characters
        if isinstance(c, dict)
    )
    style = ", ".join(
        part
        for part in (str(bible.get("style") or "").strip(), str(bible.get("realism") or "").strip())
        if part
    )
    parts = [once(package.get("subject")), once(package.get("action"))]
    for label, value in (
        ("Character", who),
        ("Environment", package.get("environment")),
        ("Camera", package.get("camera")),
        ("Lighting", package.get("lighting")),
        ("Composition", package.get("composition")),
        ("Motion", package.get("motion")),
        ("Emotion", package.get("emotion")),
        ("Background", package.get("background")),
        ("Style", style),
        ("Palette", bible.get("palette")),
        ("Continuity", package.get("continuity")),
    ):
        said = once(value)
        if said:
            parts.append(f"{label}: {said}")
    parts.append(f"Avoid: {', '.join(str(a) for a in (package.get('avoid') or [])[:6])}")
    text = " ".join(f"{part}." for part in parts if part)
    return cut_at_sentence(text, MAX_PROMPT_CHARS)


def cut_at_sentence(text: str, limit: int) -> str:
    """``text`` on one line within ``limit`` UTF-16 units, cut after its last whole sentence.

    A prompt sliced at a character count ends mid-word, and the model reads the fragment as
    an instruction. With no sentence end inside the limit the cut is at the last whole word;
    only a single word longer than the limit is cut inside itself.
    """
    said = " ".join(str(text or "").split())
    if limit <= 0:
        return ""
    if lint.utf16_units(said) <= limit:
        return said
    used = 0
    end = 0
    for index, char in enumerate(said):
        used += lint.utf16_units(char)
        if used > limit:
            break
        end = index + 1
    head = said[:end]
    stops = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", said[: end + 1]) if m.end() <= end]
    if stops:
        return head[: stops[-1]]
    if said[end : end + 1] == " ":
        return head.rstrip()
    if " " in head:
        return head.rsplit(" ", 1)[0].rstrip(" ,;:")
    return head


# ------------------------------------------------------------------ the compiler
#
# compile_prompts (2026-09-27, after the Nepal film): two prompts per filmed scene, each
# written for the model that reads it, from the shot plan's package and the film's bible.
#
# - The still prompt goes to the image model (seedream5_pro): 60-120 words of plain
#   photographic English that open with the film's look block, then the frame (shot size,
#   lens, angle), the subject, the people as the bible allows them, a 9:16 composition
#   with the lower quarter calm for captions, and the light. No codes, no hex, no "Camera:"
#   or "Motion:" line, no quotations, no "Avoid:" list: at most two inline exclusions.
# - The motion prompt goes with the approved still to the video model: 20-70 words that
#   never describe the picture again, only exactly one camera move from the enum, one motion
#   of the world, one speed word, and the closing line. Each video model has its dialect:
#   veo takes its exclusions as negativePrompt nouns and no negation in its promptText;
#   seedance and wan take short constraint sentences; Runway gen4 only positive words.
# - Caps come from the model's contract and are met by leaving out whole sentences, the
#   least important first, never by slicing.

LIVE_KIND = "LIVE"
DEFAULT_STILL_MODEL = "seedream5_pro"
DEFAULT_MOTION_MODEL = "seedance2_5"
STILL_MAX_WORDS = lint.STILL_WORDS[1]
MOTION_MIN_WORDS, MOTION_MAX_WORDS = lint.MOTION_WORDS

# «Mișcare v2» (the Owner, 2026-10-11, on the live clips of film aa170155 and the serial's
# first board f06808c9: «Pe video pare doar un zoom, și mișcări mici. Nu este capabil de mai
# mult? De cursivitate? De mișcări mai ample?»). The prompts asked for exactly that: «Slow
# push-in toward the subject.», «Static camera, held steady.», «Background details remain
# stable throughout the shot.», «barely moving». A video model does what it is told. Every
# move below is now said with its tempo and its path (where it starts, where it ends), a clip
# of TWO_BEAT_SECONDS or more gets a second beat of camera (the move eases into a hold), the
# plan's action is said as the subject's own movement, and the world keeps moving. What
# protects the picture stays: one move per clip, no text, faces as the bible says, the
# identity and continuity sentences, the closing line; and the clip QC's floors are minimums.

#: How each camera move of the enum is said. Each sentence names exactly one move (as
#: prompt_lint.camera_moves reads it), carries its tempo (prompt_lint.SPEED_WORDS) and its
#: path, and spells its own key, so a stored package's move is readable in its prompt. The
#: older keys keep their "slow": a plan or a rewrite that names them by name asked for that.
MOVE_SENTENCES: dict[str, str] = {
    "static": (
        "Static camera on a fixed tripod, steady, the life of the scene moving inside the "
        "fixed frame."
    ),
    "slow push-in": (
        "Slow push-in from the wide view toward the subject, steady all the way, ending close "
        "on it."
    ),
    "slow pull-back": (
        "Slow pull-back from close on the subject to the wide view, steady all the way, the "
        "space opening around it."
    ),
    "dolly in": (
        "Steady dolly in from a wide view to a close framing of the subject, the foreground "
        "sliding past the lens."
    ),
    "dolly out": (
        "Steady dolly out from a close framing of the subject to a wide view, revealing the "
        "whole space around it."
    ),
    "slow pan left": (
        "Slow pan left, smooth and with a clear start and end, sweeping from the right side "
        "of the scene across to the subject."
    ),
    "slow pan right": (
        "Slow pan right, smooth and with a clear start and end, sweeping from the left side "
        "of the scene across to the subject."
    ),
    "tracking left": (
        "Steady tracking left alongside the subject at walking pace, the background sliding "
        "past behind it."
    ),
    "tracking right": (
        "Steady tracking right alongside the subject at walking pace, the background sliding "
        "past behind it."
    ),
    "tilt up": (
        "Smooth tilt up from the base of the scene to its top, steady, ending on the subject."
    ),
    "tilt down": (
        "Smooth tilt down from the top of the scene, steady, settling on the subject below."
    ),
    "aerial drift forward": (
        "Steady aerial drift forward over the scene, the ground sliding beneath, the horizon "
        "opening ahead."
    ),
    "pedestal up": (
        "Steady pedestal up from low at the subject to eye level, the scene rising into view "
        "behind it."
    ),
    "crane up": (
        "Steady crane up from the subject, rising and revealing the whole scene below as the "
        "camera climbs."
    ),
    "crane down": (
        "Steady crane down from high above, descending and settling on the subject as the "
        "scene closes in around it."
    ),
    "slow orbit": (
        "Slow orbit around the subject, steady, a quarter turn from its left side to its "
        "front, the background wheeling behind it."
    ),
    "handheld drift": (
        "Smooth handheld drift, the frame alive and easing slowly from the left of the "
        "subject toward its centre through the whole shot."
    ),
    "rack focus": (
        "Smooth rack focus from the foreground to the subject behind it, the focus pulling "
        "steadily as the subject moves."
    ),
}
#: The move said for an intent whose move is not in the table (a package edited by hand).
DEFAULT_MOVE = "dolly in"

#: The moves that suit each shot size, best first, for a plan that named none. "static" is
#: never chosen for a plan that did not ask for it: the Nepal clips, asked for "no camera
#: movement" on every scene, came back almost still (mean YDIF about 1.1 of 255). Nor are
#: "slow orbit" and "rack focus": an orbit turns the people in frame toward the camera, a
#: rack focus moves nothing by itself; both are a plan's deliberate choice, never a default.
SIZE_MOVES: dict[str, tuple[str, ...]] = {
    "aerial": ("aerial drift forward", "crane up", "tracking right", "dolly in"),
    "wide": ("tracking right", "dolly in", "crane up", "tracking left", "dolly out"),
    "medium": ("dolly in", "tracking left", "crane down", "handheld drift"),
    "close": ("dolly in", "crane down", "tracking right", "tilt up"),
    "detail": ("dolly in", "crane down", "tilt down", "pedestal up"),
}
#: A clip this long gets two beats of camera: the move, then (said without "then") a hold.
TWO_BEAT_SECONDS = 7.0
#: The second beat: the move eases into a hold while the scene goes on moving. Said in words
#: that name no move of the enum, so the prompt still names exactly one (CAMERA_COUNT).
END_BEAT = (
    "In the final seconds the camera eases to a steady hold on the subject, and everything "
    "in the frame keeps moving."
)
#: The amplitude of a shot's movement: AMPLE is the rule; MEASURED is one step down, for a
#: redo of a clip whose movement deformed the picture (clip QC: faces, warping, a broken
#: shot). The Director's rewrite may set ``motion_amplitude`` on the package; the compiler
#: never dials it down by itself.
AMPLE = "ample"
MEASURED = "measured"
AMPLITUDES = (AMPLE, MEASURED)
MEASURED_SENTENCE = (
    "The move stays smooth and moderate, and every shape and edge keeps its form from the "
    "first frame to the last."
)

COMPOSITION_SENTENCE = (
    "Vertical 9:16 frame, main subject in the upper two thirds, lower quarter calm and uncluttered."
)
STILL_EXCLUSIONS = "No text, no logo."
PEOPLE_SENTENCE = (
    "Any people appear only as small distant figures seen from behind, faces turned away."
)
#: The bible's face rule said for a scene that shows nobody: it never asks for figures, and
#: the linter reads it as the rule kept (`prompt_lint.NO_FACE_STATED`).
NO_PEOPLE_SENTENCE = "There are no people in the frame."
FACES_CONSTRAINT = "Faces stay turned away from the camera."
#: Said when a motion prompt is under its word floor. Until 2026-10-11: "The movement stays
#: smooth and unhurried." (prompt_lint.LEGACY_STILLNESS).
MOTION_PAD = "Everything in the frame keeps moving smoothly through the whole clip."
#: The world's motion when the plan names none. Setting-neutral: an airless scene gets no
#: haze or wind from it. Until 2026-10-11: "Background details remain stable throughout the
#: shot." — the stillness the Owner then saw in every clip.
DEFAULT_WORLD_MOTION = (
    "Shadows drift and the light shifts across the scene, its smallest details stirring."
)
#: A chain word inside a plan's motion or action, read for the video model: the chain is
#: wanted (it is the clip's sequence), the word is not (THEN_CHAIN blocks on seedance), so
#: "pauses, then lays the pen flat" is said as "pauses, lays the pen flat". "Since then",
#: "by then", "back then" are about the past and stay (prompt_lint.STILL_THEN's rule).
_CHAIN_WORD = re.compile(
    r",?\s*\b(?:(?:and\s+)?(?<!\bsince )(?<!\buntil )(?<!\btill )(?<!\bby )(?<!\bback )"
    r"(?<!\beven )(?<!\bjust )then|after\s+that|afterwards|next,)\b\s*,?\s*",
    re.IGNORECASE,
)
VEO_NEGATIVE = ("text", "subtitles", "logo", "watermark")
VEO_FACES = "human faces"

_COLOUR_WORDS = re.compile(
    r"\b(?:blue|blues|gold|golden|grey|gray|greys|brown|browns|green|greens|red|reds|amber"
    r"|ochre|teal|orange|yellow|purple|violet|pink|crimson|beige|cyan|magenta|silver"
    r"|palette|hue|tones?)\b",
    re.IGNORECASE,
)
_CAMERA_WORDS = re.compile(
    r"\b(?:camera|lens|shot|pan|pans|panning|tilt\w*|zoom\w*|dolly|static|locked|tracking"
    r"|handheld|orbit\w*|push|pull|crane|frame|framing|angle|movement)\b",
    re.IGNORECASE,
)
_PERCENT = re.compile(r"\d\s?%|\bper\s?cent\b", re.IGNORECASE)
_FACE_KEPT = re.compile(r"\bfrom\s+behind\b|\bdistant\b", re.IGNORECASE)
_QUOTE_MARKS = re.compile('["“”„]')
_NOT_A_PERSON = re.compile(r"\b(?:no|without|not\s+a|zero)\s+(?:\w+\s+)?$")


#: A pointer at another scene said after what it qualifies, with the words that carry it:
#: "the void of scenes 2 and 3", "the tunnel from scene 1", "a tunnel similar to scene 2's",
#: "drift as in scene 2", "a street seen in the previous scene".
_TRAILING_POINTER = re.compile(
    r"(?:\s*,)?\s+(?:(?:seen|shown|used|introduced|established)\s+)?"
    r"(?:(?:similar|identical|equal|comparable)\s+)?"
    r"(?:as|like|from|of|in|than|to)\s+(?:in\s+)?(?:the\s+)?"
    rf"(?:{lint.SCENE_REFERENCE.pattern})\s*$",
    re.IGNORECASE,
)
#: A pointer said as the owner or the label of a thing: "scene 1's tunnel", "the previous
#: scene's street", "the scene 1 tunnel". What is left is the thing itself: "the tunnel".
_OWNING_POINTER = re.compile(
    rf"(?:\bthe\s+)?(?:{lint.SCENE_REFERENCE.pattern})(?<='s)\s+"
    rf"|\bthe\s+(?:{lint.SCENE_NUMBERED})\s+(?=[a-z])",
    re.IGNORECASE,
)
#: "Identical to the tunnel": once the pointer is gone, the likeness points at nothing.
_LIKENESS = re.compile(
    r"^(?:the\s+)?(?:same|identical|similar|matching)\s+(?:to|as)\s+", re.IGNORECASE
)
#: "The same void as scene 2": once the pointer is gone, "same" points at nothing.
_SAME_AS = re.compile(r"\b(?:same|identical|matching)\s+", re.IGNORECASE)
#: What a pointer leaves when it was not said around a whole picture: "Back tunnel" (from
#: "Back in the scene 1 tunnel"), "to the tunnel", "A tunnel similar", "lit the same".
_BROKEN_START = re.compile(
    r"^(?:back|again|once|still|also|too|to|of|as|than|like|from|by|with|for|and|or|but"
    r"|similar|identical|same|matching)\b",
    re.IGNORECASE,
)
_BROKEN_END = re.compile(
    r"\b(?:similar|identical|same|like|matching|equal|comparable)$", re.IGNORECASE
)
#: A plan that asks for a layout around its pictures: "Split screen of the forest and the
#: cleared land", "A before-and-after view of the glacier". What follows is said as one.
_PANEL_FRAMING = re.compile(
    r"^(?:(?:a|an|the)\s+)?(?:split[- ]?screen|before[- ]and[- ]after|side[- ]by[- ]side"
    r"|diptych|triptych|polyptych|montage|(?:photo\s+)?collage)"
    r"(?:\s+(?:views?|images?|shots?|comparisons?|pictures?|photos?|frames?|panels?"
    r"|compositions?|layouts?))?\s+(?:of|showing|with|between|comparing)\s+",
    re.IGNORECASE,
)
#: "The street before and after the flood": the first moment is "before the flood".
_BEFORE_AND_AFTER = re.compile(r"\bbefore[- ]and[- ]after\b(?=\s+\w)", re.IGNORECASE)


def without_scene_reference(part: str) -> str:
    """The clause with its pointer at another scene taken out; "" when nothing whole is left.

    An image or video model cannot know what "scene 1" looks like (film babcf272, 2026-10-09:
    "the identical tunnel from scene 1"). A pointer said after a whole picture or as its
    owner leaves that picture: "The same near-black void as scene 2" is "The near-black
    void", "scene 1's tunnel" is "the tunnel". Any other pointer takes its clause with it
    ("Back in the scene 1 tunnel" left "Back tunnel"; review, 2026-10-09).
    """
    if not lint.SCENE_REFERENCE.search(part):
        return part
    left = _OWNING_POINTER.sub("the ", _TRAILING_POINTER.sub("", part))
    left = _SAME_AS.sub("", _LIKENESS.sub("", left.strip()))
    left = " ".join(left.split()).strip(" ,;:-'")
    if (
        len(left.split()) < 2
        or lint.SCENE_REFERENCE.search(left)
        or lint.dangling(left)
        or not re.search(r"[A-Za-z]", left)
        or _BROKEN_START.match(left)
        or _BROKEN_END.search(left)
    ):
        return ""
    return left


def _then_head(part: str, start: int) -> str:
    """The words of a clause before its later moment, without a hanging "and"."""
    head = part[:start].rstrip(" ,;:-")
    return re.sub(r"(?:\s+\b(?:and|or|but)\b)+$", "", head, flags=re.IGNORECASE).strip()


def _clauses_of(text: Any, *, motion: bool = False) -> list[str]:
    """The clauses of a plan field that may enter a prompt, in the plan's words.

    Dropped: codes, hex colours (their parentheses too), a negation ("no camera movement"
    is still about the camera), a percentage, a chart, a black screen or a title (those
    scenes are composed locally), writing, a quotation, a label such as "Direction:", a
    value that says nothing ("None", "n/a"), the head of a broken sentence (a clause that
    ends in "the", "of", "and"...), and a pointer at another scene ("from scene 1"; the rest
    of its clause stays when it is whole). For the motion prompt also anything about the
    camera, a colour or a "then" chain.

    The still prompt is one moment, the first frame of the shot (film babcf272, 2026-10-09:
    a field that listed three moments came back as three stacked panels). Its fields are
    read up to the first later moment: the words before a "then", "dissolves into" or "cuts
    to" are kept, and the rest of that clause and every later clause of the field are not
    ("finally", "later", "next", "secondly"...). A field that says "First ..." is read for
    that first moment only. A later-moment word that opens the field is about the scene
    before it ("Finally, the cluster settles" is this shot's one moment) and is taken off.
    A layout is read as its first picture: "Before: X. After: Y" is X, "Split screen of X"
    is X, "the street before and after the flood" is "the street before the flood". A
    parenthetical aside is closed up, never split into fragments (prompt_lint.without_asides).
    """
    said = _flatten(text).replace("’", "'").replace("‘", "'")
    said = lint.without_asides(re.sub(r"\(\s*\)", "", _HEX_COLOUR.sub("", said)))

    def usable(part: str) -> str:
        part = without_scene_reference(part)
        if (
            not re.search(r"[A-Za-z]", part)
            or lint.NONE_WORD.match(part)
            or lint.dangling(part)
            or lint.ENUM_CODE.search(part)
            or lint.NEGATION.search(part)
            or lint.INLINE_EXCLUSION.search(part)
            or _PERCENT.search(part)
            or lint.classify_kind_phrase(part)
            or _TEXT_REQUEST.search(part)
            or _QUOTE_MARKS.search(part)
        ):
            return ""
        if motion and (
            _CAMERA_WORDS.search(part) or lint.camera_moves(part) or lint.THEN_CHAIN.search(part)
        ):
            return ""
        return part

    kept: list[str] = []
    opened = False  # a clause of the field has been read
    first_only = False  # the field said "First ...": a still shows that moment only
    panelled = False  # a clause was labelled as one picture of a layout ("Before:")
    for clause in re.split(r"[;,.!?]\s*|\s*\(|\)\s*|\s+-{1,2}\s+|\s*—\s*", said):
        raw = " ".join(clause.split()).strip(" -:/")
        if motion:
            part = usable(_LABEL_PREFIX.sub("", raw))
            if part:
                kept.append(part)
            continue
        if not re.search(r"[A-Za-z]", raw):
            continue
        if lint.PANEL_LABEL.match(raw):
            if panelled:
                break
            panelled = True
        part = _LABEL_PREFIX.sub("", raw)
        part = _BEFORE_AND_AFTER.sub("before", _PANEL_FRAMING.sub("", part))
        first = lint.FIRST_OPENER.match(part)
        if first:
            first_only = True
            part = part[first.end() :]
        elif not opened:
            part = lint.LATER_START.sub("", part)
        elif lint.SEQUENCE_OPENER.match(part):
            break
        opened = True
        marks = [
            found.start()
            for found in (lint.STILL_THEN.search(part), lint.LATER_MOMENT.search(part))
            if found
        ]
        if marks:
            head = usable(_then_head(part, min(marks)))
            if head:
                kept.append(head)
            break
        said_something = bool(re.search(r"[A-Za-z]", part))
        part = "" if lint.PANEL_LAYOUT.search(part) else usable(part)
        if part:
            kept.append(part)
        if first_only and said_something:
            break
    return kept


def _phrase(clauses: list[str], max_words: int) -> str:
    """Whole clauses joined while they fit ``max_words``; a first clause alone that does
    not fit is kept to its first ``max_words`` words, never ending on "the", "of" or "and"
    (a subject that is one long sentence still names its subject)."""
    fitted: list[str] = []
    count = 0
    for clause in clauses:
        words = len(clause.split())
        if count + words > max_words:
            if not fitted:
                head = clause.split()[:max_words]
                while len(head) > 1 and lint.dangling(" ".join(head)):
                    head.pop()
                fitted.append(" ".join(head))
            break
        fitted.append(clause)
        count += words
    return ", ".join(fitted)


def _sentence(text: str) -> str:
    said = " ".join(str(text or "").split()).strip(" ,;:")
    if not said:
        return ""
    said = said[:1].upper() + said[1:]
    return said if said.endswith((".", "!", "?")) else f"{said}."


def _person_window(text: str, start: int) -> str:
    """The words around a person mention, as prompt_lint reads them: its own sentence,
    three words before and six after."""
    offset = 0
    for sentence in re.split(r"(?<=[.!?;])\s+", text):
        begin = text.find(sentence, offset)
        if begin <= start < begin + len(sentence):
            words = list(re.finditer(r"\S+", sentence))
            index = next(
                (i for i, w in enumerate(words) if w.start() <= start - begin < w.end()), 0
            )
            first = words[max(0, index - 3)].start()
            last = words[min(len(words) - 1, index + 6)].end()
            return sentence[first:last]
        offset = begin + len(sentence)
    return ""


def hide_faces(text: str) -> str:
    """Every person the text shows, kept from behind: "seen from behind" is added after a
    person mention that has neither "from behind" nor "distant" among its nearby words."""
    said = text
    for _ in range(32):
        changed = False
        for match in lint.PERSON.finditer(said):
            before = said[max(0, match.start() - 16) : match.start()].lower()
            if _NOT_A_PERSON.search(before):
                continue
            if _FACE_KEPT.search(_person_window(said, match.start())):
                continue
            said = f"{said[: match.end()]} seen from behind{said[match.end() :]}"
            changed = True
            break
        if not changed:
            break
    return said


#: Who else a shot may show, besides the linter's people (`prompt_lint.PERSON`): the trades a
#: factual film names (a physicist at a bench), someone said by a pronoun, and the parts of a
#: person a face rule leaves in frame. Read only to decide whether a scene shows anybody, so a
#: scene of objects can be said to be empty (`NO_PEOPLE_SENTENCE`); a word missed here only
#: keeps the older sentence, never a face.
_ALSO_PEOPLE = re.compile(
    r"\b(?:scientists?|physicists?|chemists?|engineers?|researchers?|technicians?|operators?"
    r"|astronauts?|cosmonauts?|inventors?|professors?|teachers?|assistants?|pilots?|crew"
    r"|staff|team|audience|spectators?|passengers?|drivers?|miners?|sailors?|guards?|police"
    r"|firefighters?|athletes?|players?|dancers?|musicians?|artists?|writers?|journalists?"
    r"|reporters?|customers?|visitors?|tourists?|scholars?|colleagues?|someone|somebody"
    r"|anyone|everyone|he|she|him|his|her|hers|hands?|fingers?|silhouettes?|humans?"
    r"|individuals?|adults?|youths?|teens?|teenagers?|babies|baby|guests?|patients?)\b",
    re.IGNORECASE,
)


def _shows_people(text: str) -> bool:
    for pattern in (lint.PERSON, _ALSO_PEOPLE):
        for match in pattern.finditer(text):
            if match.group(0).lower() == "hand" and text[match.end() :].startswith("-drawn"):
                continue
            before = text[max(0, match.start() - 16) : match.start()].lower()
            if not _NOT_A_PERSON.search(before):
                return True
    return False


def shot_frame(camera: Any, shot_type: Any = "") -> tuple[str, str]:
    """(size, sentence) of the plan's frame: the shot size, the lens and the angle, in
    words. Anything the plan said about moving the camera stays out of the still."""
    text = f"{_flatten(camera)} ".lower()
    fallback = str(shot_type or "").lower().replace("_", " ")
    size = ""
    label = ""
    for source in (text, fallback):
        if re.search(r"extreme\s+wide", source):
            size, label = "wide", "Extreme wide shot"
        elif re.search(r"\baerial\b|\bdrone\b|bird'?s[- ]eye", source):
            size, label = "aerial", "Aerial wide shot"
        elif re.search(r"medium[- ](?:wide|long)", source):
            size, label = "wide", "Medium wide shot"
        elif re.search(r"\bwide\b|\bestablishing\b|\blong shot\b", source):
            size, label = "wide", "Wide establishing shot"
        elif re.search(r"medium[- ]close", source):
            size, label = "close", "Medium close-up shot"
        elif re.search(r"extreme\s+close|\bmacro\b|\bdetail\b|\binsert\b", source):
            size, label = "detail", "Detail shot"
        elif re.search(r"close[- ]?up|closeup", source):
            size, label = "close", "Close-up shot"
        elif re.search(r"\bmedium\b|\bmid[- ]shot\b", source):
            size, label = "medium", "Medium shot"
        if size:
            break
    if not size:
        size, label = "medium", "Medium shot"
    parts = [label]
    lens = re.search(r"\b(\d{2,3})\s?mm\b", text)
    if lens:
        parts.append(f"{lens.group(1)}mm lens")
    angle = re.search(r"\b(low|high|eye[- ]level|overhead|top[- ]down)(?:\s+angle)?\b", text)
    if angle:
        word = angle.group(1).replace(" ", "-")
        parts.append(word if word in ("overhead", "top-down") else f"{word} angle")
    return size, _sentence(", ".join(parts))


def choose_camera_move(
    package: dict[str, Any],
    size: str,
    previous: list[str] | tuple[str, ...] = (),
    *,
    avoid: Sequence[str] = (),
) -> str:
    """The one camera move a scene's clip makes.

    The plan's own choice wins: its ``camera_move`` field, else the one move its camera
    text names ("static" and "no movement" name none). Otherwise the move that suits the
    shot size, never the move of the scene before, so the film's camera varies, and none of
    ``avoid`` (the compiler keeps an orbit away from people shown from behind: a quarter
    turn around them shows their faces).
    """
    stated = str(package.get("camera_move") or "").strip().lower()
    if stated in lint.CAMERA_MOVES:
        return stated
    named = [
        move for move, _ in lint.camera_moves(_flatten(package.get("camera"))) if move != "static"
    ]
    if len(named) == 1:
        return named[0]
    choices = SIZE_MOVES.get(size) or SIZE_MOVES["medium"]
    last = previous[-1] if previous else None
    allowed = [move for move in choices if move not in avoid] or list(choices)
    return next((move for move in allowed if move != last), allowed[0])


def _fit_sentences(items: list[tuple[int, int, str]], cap: int, max_words: int) -> str:
    """Sentences chosen by rank (0 first), said in their order.

    First the word budget decides what the prompt says; then the contract's cap (UTF-16
    units) takes whole sentences out of that prompt, the least important first, so a capped
    prompt is always the uncapped one with sentences left out, never a slice of it. When
    not even one sentence fits the cap, the first is cut at its last whole word.
    """

    def choose(pool: list[tuple[int, int, str]], limit: int | None) -> list[tuple[int, str]]:
        chosen: list[tuple[int, str]] = []
        for _rank, order, text in sorted(pool):
            if not text:
                continue
            candidate = " ".join(t for _, t in sorted([*chosen, (order, text)]))
            if len(candidate.split()) <= max_words and (
                limit is None or lint.utf16_units(candidate) <= limit
            ):
                chosen.append((order, text))
        return chosen

    said = {order for order, _ in choose(items, None)}
    chosen = choose([item for item in items if item[1] in said], cap)
    if not chosen:
        first = next((text for _rank, _order, text in sorted(items) if text), "")
        return cut_at_sentence(first, cap)
    return " ".join(text for _, text in sorted(chosen))


def _motion_family(model_id: Any) -> str | None:
    return lint.model_family(model_id) if isinstance(model_id, str) else None


def _contract_model(contract: Any, key: str, default: str) -> str:
    if isinstance(contract, dict):
        for name in (key, "model") if key == "model_id" else (key,):
            value = contract.get(name)
            if isinstance(value, str) and value:
                return value
    return default


def _continuous(text: Any) -> str:
    """A plan's motion or action as one continuous movement: its chain words taken out, the
    chain itself kept ("taps the pen, pauses, then lays it flat" is the clip's sequence)."""
    return " ".join(_CHAIN_WORD.sub(", ", _flatten(text)).replace(" ,", ",").split())


def _seconds_of(package: dict[str, Any]) -> float:
    """The scene's planned length in seconds, 0 when the package does not say."""
    value = package.get("seconds")
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return 0.0
    try:
        return max(0.0, float(value))
    except ValueError:
        return 0.0


def _motion_intent(
    package: dict[str, Any], move: str, faces_banned: bool, people: bool
) -> dict[str, Any]:
    """What moves in the scene, model-neutral: the move, the world's motion, the subject's,
    the clip's length and the movement's amplitude.

    The world's motion is the first clause of the plan's motion, then its action, then its
    environment, that names something the world does (cloud, wind, dust, shadows, curtains)
    in at least three words; the subject's is what else the plan's motion says, and then
    every clause of the plan's action that carries a verb of motion (prompt_lint.
    SUBJECT_MOTION: stands, walks to the window, turns, hands over the ledger; spins, pulses)
    and was not said already. Neither describes the picture. Chains are kept as sequences
    without their "then" (`_continuous`).
    """
    from_motion = _clauses_of(_continuous(package.get("motion")), motion=True)
    from_action = _clauses_of(_continuous(package.get("action")), motion=True)
    candidates = [
        *from_motion,
        *from_action,
        *_clauses_of(package.get("environment"), motion=True),
    ]
    world = next(
        (
            clause
            for clause in candidates
            if lint.ENVIRONMENT_MOTION.search(clause)
            and not _shows_people(clause)
            and len(clause.split()) >= 3
        ),
        "",
    )
    subject_clauses = [c for c in from_motion if c != world]
    said = {clause.casefold() for clause in subject_clauses} | {world.casefold()}
    action_clauses: list[str] = []
    for clause in from_action:
        key = clause.casefold()
        if key in said or not lint.SUBJECT_MOTION.search(clause):
            continue
        said.add(key)
        action_clauses.append(clause)
    subject = ", ".join(subject_clauses)
    amplitude = str(package.get("motion_amplitude") or AMPLE).strip().lower()
    return {
        "camera_move": move,
        "world": _sentence(_phrase([world], 14)) if world else DEFAULT_WORLD_MOTION,
        "subject": _sentence(subject),
        "subject_clauses": [_sentence(clause) for clause in subject_clauses],
        "action_clauses": [_sentence(clause) for clause in action_clauses],
        "seconds": _seconds_of(package),
        "amplitude": amplitude if amplitude in AMPLITUDES else AMPLE,
        "constraints": _scene_constraints(package),
        "faces_banned": faces_banned,
        "people": people,
    }


def _intent_clauses(intent: dict[str, Any], key: str) -> list[str]:
    """A stored intent's list of sentences under ``key``; none for an intent from before."""
    value = intent.get(key)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def render_motion(
    intent: dict[str, Any], family: str | None, cap: int = lint.DEFAULT_PROMPT_MAX_UTF16
) -> tuple[str, str | None]:
    """(promptText, negativePrompt or None) for one video model, from a motion intent.

    The camera's move with its path and tempo opens; the world's motion follows; then every
    clause of the plan's motion and the action's verbs of motion, each its own sentence; a
    clip of TWO_BEAT_SECONDS or more ends its camera on a hold (END_BEAT); a MEASURED
    amplitude says the move stays moderate and the shapes keep their form; the face rule and
    the closing line end it. A stored intent of a film planned before 2026-10-11 is said in
    these words too: its stillness world ("remain stable") is replaced, its missing length
    reads as one beat.
    """
    move = str(intent.get("camera_move") or "")
    camera = MOVE_SENTENCES.get(move, MOVE_SENTENCES[DEFAULT_MOVE])
    positive_only = family in ("veo", "gen4")
    closing = lint.VEO_MOTION_CLOSING if positive_only else lint.MOTION_CLOSING
    faces = bool(intent.get("faces_banned"))
    constraint = FACES_CONSTRAINT if faces and intent.get("people") and family != "veo" else ""
    negative = None
    if family == "veo":
        negative = ", ".join(
            [*((VEO_FACES,) if faces else ()), *VEO_NEGATIVE, *(intent.get("constraints") or [])]
        )
    # Every clause of the plan's motion, each its own sentence, in the plan's order: the
    # motion prompt names the visible subject in full (2026-10-11, aa170155 scene 4: "Slow
    # pull-back that widens the view. Dust motes drift slowly in the beam" named nothing, and
    # the model improvised people; the Director's brief named it). The plan's exclusions are
    # never said as "no ...": a video model reads the words, not the negation; they reach the
    # negative channel of a model that has one.
    clauses = intent.get("subject_clauses")
    subjects = clauses if isinstance(clauses, list) else [str(intent.get("subject") or "")]
    actions = _intent_clauses(intent, "action_clauses")
    world = str(intent.get("world") or "")
    if not world or world in lint.LEGACY_STILLNESS:
        world = DEFAULT_WORLD_MOTION
    amplitude = str(intent.get("amplitude") or AMPLE)
    seconds = _seconds_of(intent)
    two_beats = amplitude != MEASURED and move != "static" and seconds >= TWO_BEAT_SECONDS
    items = [
        (0, 0, camera),
        (4, 1, world),
        *[(2, 10 + index, str(clause)) for index, clause in enumerate(subjects)],
        *[(3, 100 + index, clause) for index, clause in enumerate(actions)],
        (5, 800, END_BEAT if two_beats else ""),
        (1, 850, MEASURED_SENTENCE if amplitude == MEASURED else ""),
        (0, 900, constraint),
        (0, 1000, closing),
    ]
    prompt = _fit_sentences(items, cap, MOTION_MAX_WORDS)
    if len(prompt.split()) < MOTION_MIN_WORDS:
        prompt = _fit_sentences([*items, (6, 8, MOTION_PAD)], cap, MOTION_MAX_WORDS)
    return prompt, negative


def _scene_constraints(package: dict[str, Any]) -> list[str]:
    """The plan's own exclusions as plain nouns for a model's negative channel (veo's
    negativePrompt); the generic text/face rules already have their channels.

    Camera instructions are represented by the one selected move, never repeated as a
    competing move in a constraint. No physical detail is inferred from an exclusion, and
    none is ever said in a positive prompt as "no ...".
    """
    generic = {item.casefold() for item in DEFAULT_NEGATIVES}
    result: list[str] = []
    for item in package.get("avoid") or []:
        text = " ".join(str(item).split()).strip(" .")
        if not text or text.casefold() in generic or _CAMERA_WORDS.search(text):
            continue
        if lint.ENUM_CODE.search(text) or _HEX_COLOUR.search(text):
            continue
        text = re.sub(r"^(?:avoid|no|without)\s+", "", text, flags=re.IGNORECASE)
        if text and text.casefold() not in {value.casefold() for value in result}:
            result.append(text)
    return result


def compile_prompts(
    package: dict[str, Any],
    bible: dict[str, Any] | None,
    contract: dict[str, Any] | None = None,
    *,
    previous_moves: list[str] | tuple[str, ...] = (),
    look: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The still prompt, the motion prompt and the negative prompt for one scene.

    ``contract`` names the video model (``model_id``), optionally the still model
    (``still_model_id``, seedream5_pro by default), and the prompt caps as the vendor's
    contract states them (``prompt_max``, an int or a per-task dict; 1000 UTF-16 units by
    default). A scene composed locally (DATA_CARD, TITLE_CARD, BLACK) gets no prompt at all:
    it never reaches a paid model. Deterministic: the same package gives the same prompts.
    """
    kind = str(package.get("scene_kind") or LIVE_KIND).upper()
    bible = bible if isinstance(bible, dict) else {}
    motion_model = _contract_model(contract, "model_id", DEFAULT_MOTION_MODEL)
    family = _motion_family(motion_model)
    if kind != LIVE_KIND:
        return {
            "scene_kind": kind,
            "still_prompt": "",
            "motion_prompt": "",
            "negative_prompt": None,
            "look_block": "",
            "camera_move": "",
            "shot_size": "",
            "motion_family": family or "generic",
            "motion_intent": None,
        }
    faces_banned = bool(lint.bible_face_rule(bible))
    still_family = _motion_family(_contract_model(contract, "still_model_id", DEFAULT_STILL_MODEL))
    factual_look = look or load_factual_look()
    # A scene's own place and light are authoritative: the look's place, season, weather and
    # daylight are left unsaid where the scene names its own (2026-10-11, aa170155: "A real
    # location as it is today, Early autumn, None indoors. Soft diffuse daylight" over a
    # 1930s lamp-lit desk at night drew the daylight and a beige lamp). The rendering, the
    # palette, the lens and the grain stay: they are the one look of the film.
    omit: set[str] = set()
    if _clauses_of(package.get("environment")):
        omit |= PLACE_SLOTS
    if _clauses_of(package.get("lighting")):
        omit |= LIGHT_SLOTS
    block = look_block(bible, factual_look, omit=omit)
    size, frame = shot_frame(package.get("camera"), package.get("shot_type"))

    def said(field: str) -> str:
        text = _sentence(", ".join(_clauses_of(package.get(field))))
        return hide_faces(text) if faces_banned else text

    subject = said("subject")
    action = said("action")
    if action and subject and action.casefold() == subject.casefold():
        action = ""
    environment = said("environment")
    if environment and environment.casefold() in (subject.casefold(), action.casefold()):
        environment = ""
    light = ", ".join(_clauses_of(package.get("lighting")))
    if light and not re.search(r"\blight", light, re.IGNORECASE):
        # "The glow of the spheres" (babcf272) said as "Light The glow of ..." was no sentence.
        if re.match(r"(?:the|a|an|its|their|his|her|this|that|one)\b", light, re.IGNORECASE):
            light = f"lit by {light[:1].lower()}{light[1:]}"
        else:
            light = f"light {light}"
    cast = _cast_sentence(package.get("characters"), faces_banned)
    people = _shows_people(" ".join((subject, action, environment, cast)))
    items = [
        (0, 0, block),
        (0, 1, frame),
        (0, 2, subject),
        (0, 3, cast),
        (3, 4, action),
        (1, 5, environment),
        # How people are kept faceless where the scene shows them; a scene of objects is said
        # to be empty of people instead. The first, said in a scene of objects, asked the model
        # for figures (2026-10-11, cyclotron scene 4: two objects on a desk came back with
        # people, and the clip turned their faces to the camera; the Director's brief named it).
        (0, 6, (PEOPLE_SENTENCE if people else NO_PEOPLE_SENTENCE) if faces_banned else ""),
        (5, 7, COMPOSITION_SENTENCE),
        (2, 8, _sentence(light)),
        # The plan's own exclusions are never said here as "no ...": an image model reads the
        # words literally (config/factual_look.json's note; the lint refuses them on veo).
        # They stay in the package's `avoid` and reach a model's negative channel where it
        # has one (`render_motion`).
        (0, 9, STILL_EXCLUSIONS if still_family != "gen4" else ""),
    ]
    still = _fit_sentences(items, lint.prompt_cap(contract, "still"), STILL_MAX_WORDS)
    # People kept faceless are shown from behind: an orbit around them turns their faces to
    # the camera, so it is never the compiler's choice for such a scene (a plan may ask).
    move = choose_camera_move(
        package, size, previous_moves, avoid=("slow orbit",) if faces_banned and people else ()
    )
    intent = _motion_intent(package, move, faces_banned, people)
    motion, negative = render_motion(intent, family, lint.prompt_cap(contract, "motion"))
    return {
        "scene_kind": kind,
        "still_prompt": still,
        "motion_prompt": motion,
        "negative_prompt": negative,
        "look_block": block,
        "camera_move": move,
        "shot_size": size,
        "motion_family": family or "generic",
        "motion_intent": intent,
    }


def _cast_sentence(characters: Any, faces_banned: bool) -> str:
    """The film's characters as the picture shows them: their look in words, never their
    name (a name means nothing to an image model and can be drawn as writing). When faces
    are forbidden, only what they wear, seen from behind."""
    described: list[str] = []
    for character in characters if isinstance(characters, list) else []:
        if not isinstance(character, dict):
            continue
        outfit = ", ".join(_clauses_of(character.get("outfit")))
        if faces_banned:
            if outfit:
                described.append(f"a figure seen from behind wearing {outfit}")
            continue
        look = ", ".join(_clauses_of(character.get("face_hair")))
        parts = [part for part in (look, f"wearing {outfit}" if outfit else "") if part]
        if parts:
            described.append(", ".join(parts))
    return _sentence("; ".join(described))


def compile_film_prompts(
    packages: list[dict[str, Any]],
    bible: dict[str, Any] | None,
    contract: dict[str, Any] | None = None,
    *,
    contracts: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """compile_prompts for every scene of a film in order, so the camera varies from one
    filmed scene to the next. ``contracts`` may give a scene (by its ``scene_index``) its
    own model's contract: the model is chosen per scene, by cost (the Owner, 2026-09-27)."""
    moves: list[str] = []
    look = load_factual_look()
    compiled: list[dict[str, Any]] = []
    for package in packages:
        index = package.get("scene_index")
        terms = (contracts or {}).get(int(index)) if isinstance(index, int) else None
        item = compile_prompts(package, bible, terms or contract, previous_moves=moves, look=look)
        if item["camera_move"]:
            moves.append(item["camera_move"])
        compiled.append(item)
    return compiled


def motion_prompt_for(
    package: dict[str, Any], model_id: Any, contract: dict[str, Any] | None = None
) -> tuple[str, str | None]:
    """(promptText, negativePrompt or None) for the model that films this scene.

    A package the compiler wrote carries its motion intent, so the prompt is said again in
    the dialect of whichever model the scene is bought on. A package from before the
    compiler has none: its stored motion prompt is used as it is (empty when it has none).
    """
    intent = package.get("motion_intent") if isinstance(package, dict) else None
    if isinstance(intent, dict) and intent.get("camera_move") in lint.CAMERA_MOVES:
        return render_motion(intent, _motion_family(model_id), lint.prompt_cap(contract, "motion"))
    stored = " ".join(str((package or {}).get("motion_prompt") or "").split())
    negative = (package or {}).get("negative_prompt")
    return stored, negative if isinstance(negative, str) and negative else None


def _run(
    engine: Engine,
    registry: Any,
    agent_id: str,
    task: str,
    prompt: str,
    template: str,
    correlation: str,
    summary: str,
    max_tokens: int,
) -> dict[str, Any] | None:
    """One agent call whose failure is a degradation, not an exception."""
    from app.agents.services import run_agent_task  # noqa: PLC0415

    try:
        result = run_agent_task(
            engine,
            registry,
            agent_id,
            task,
            prompt,
            template,
            correlation,
            summary=summary,
            max_tokens=max_tokens,
            temperature=0.3,
            emit_message=False,
        )
    except (ValueError, RuntimeError) as exc:
        logger.info("prompt_agent_unavailable", extra={"reason": str(exc)[:160]})
        return None
    if result["status"] != "SUCCEEDED" or not (result.get("output_text") or "").strip():
        logger.info("prompt_agent_no_answer", extra={"status": result["status"]})
        return None
    return result


# ------------------------------------------------------------------ learning, and the package


def prompt_lessons(session: Session, limit: int = 8) -> list[str]:
    """What the studio has learned about how its video models read instructions.

    Written after a render the Director judged: if a wording keeps producing the wrong camera
    move, that is a fact about the vendor's model, and the next prompt should know it.
    """
    from app.agents.models import MemoryRecord  # noqa: PLC0415

    rows = session.scalars(
        select(MemoryRecord)
        .where(
            MemoryRecord.memory_class == "STRATEGY",
            MemoryRecord.content.like(f"{LESSON_MARKER}%"),
            MemoryRecord.invalidated_at.is_(None),
        )
        .order_by(MemoryRecord.created_at.desc())
        .limit(limit)
    )
    return [str(row.content)[len(LESSON_MARKER) :].strip() for row in rows]


def record_prompt_lesson(session: Session, lesson: str, *, source_id: str | None = None) -> None:
    """Keep one lesson about prompting, studio-wide, with where it came from."""
    text = " ".join(str(lesson).split())[:400]
    if not text:
        return
    remember(
        session,
        memory_class="STRATEGY",
        content=f"{LESSON_MARKER} {text}",
        source_type="run" if source_id else "system",
        source_id=source_id,
        agent_id=None,
    )


def production_package(engine: Engine, storyboard_id: str) -> dict[str, Any]:
    """Everything the generator is given, and everything a person needs to audit it.

    The Owner's list, from the rows the studio already keeps: the idea and why it should
    exist, the trusted sources, the fact check, the message, the hook, the script and its
    timeline, the call to action, the visual bible, the character references, the shot list
    with a full prompt each, the audio intent, the continuity rules, the exclusions, the
    expected duration, the quality requirement and the approval status.
    """
    from app.factual.models import SourceSnapshot, TopicIdea  # noqa: PLC0415
    from app.factual.story_review import latest_review  # noqa: PLC0415

    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise PromptError(f"Storyboard {storyboard_id} not found")
        script = session.get(ScriptDraft, board.script_draft_id)
        topic = session.get(TopicIdea, script.topic_id) if script else None
        review = latest_review(session, script.id) if script else None
        claims = (
            list(
                session.scalars(
                    select(FactualClaim).where(FactualClaim.topic_id == script.topic_id)
                )
            )
            if script
            else []
        )
        sources = (
            list(
                session.scalars(
                    select(SourceSnapshot).where(SourceSnapshot.topic_id == script.topic_id)
                )
            )
            if script
            else []
        )
        scenes = list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == storyboard_id)
                .order_by(StoryboardScene.scene_index)
            )
        )
        story = dict(script.story_json or {}) if script else {}
        bible = dict(board.visual_bible_json or {})
        offset = 0.0
        timeline = []
        for scene in scenes:
            timeline.append(
                {
                    "scene_index": scene.scene_index,
                    "from_seconds": round(offset, 2),
                    "to_seconds": round(offset + float(scene.duration_seconds), 2),
                    "story_purpose": scene.story_purpose,
                    "narration": scene.voiceover_segment,
                }
            )
            offset += float(scene.duration_seconds)
        return {
            "idea": {
                "title": topic.title if topic else "",
                "topic": topic.topic if topic else "",
                "angle": topic.angle if topic else "",
                "scores": dict(topic.scores_json or {}) if topic else {},
            },
            "why_this_video_should_exist": dict(topic.thesis_json or {}) if topic else {},
            "trusted_sources": [
                {"url": s.url, "publisher": s.publisher, "fetched_at": s.fetched_at}
                for s in sources
            ],
            "fact_check": [
                {"claim": c.claim_text, "status": c.status, "confidence": c.confidence}
                for c in claims
            ],
            "core_message": story.get("core_message", ""),
            "audience_takeaway": story.get("takeaway", ""),
            "hook": story.get("hook", ""),
            "script": {
                "title": script.title if script else "",
                "voiceover": script.voiceover_full_text if script else "",
                "target_seconds": script.target_duration_seconds if script else 0,
                "estimated_seconds": story.get("estimated_seconds"),
            },
            "timeline": timeline,
            "cta": {"text": story.get("cta", ""), "kind": story.get("cta_kind", "")},
            "master_visual_bible": bible,
            "character_references": [
                ref for scene in scenes for ref in (scene.character_ids_json or [])
            ],
            "shot_list": [
                {
                    "scene_index": scene.scene_index,
                    "story_purpose": scene.story_purpose,
                    "seconds": scene.duration_seconds,
                    "prompt": scene.visual_prompt,
                    "package": dict(scene.prompt_json or {}),
                }
                for scene in scenes
            ],
            "audio_intent": [
                {
                    "scene_index": scene.scene_index,
                    "intent": (scene.prompt_json or {}).get("audio_intent", ""),
                }
                for scene in scenes
            ],
            "continuity_rules": bible.get("continuity_rules", []),
            "negative_constraints": bible.get("avoid", list(DEFAULT_NEGATIVES)),
            "expected_duration_seconds": round(offset, 2),
            "quality_requirement": bible.get("quality_target", ""),
            "approval": {
                "script_status": script.status if script else "",
                "storyboard_status": board.status,
                "story_review": review.verdict if review else "NONE",
                "story_review_at": review.created_at if review else None,
                # Who let the story through, as the record says (S10): a serial episode the
                # Owner approved without the Director's reading reads as his approval here,
                # never as her review. A factual script has no source and shows None.
                "story_review_source": (review.notes_json or {}).get("source") if review else None,
                "approved_by": (review.notes_json or {}).get("approved_by") if review else None,
                "director_review": (
                    (review.notes_json or {}).get("director_review") if review else None
                ),
                "story_review_notes": (
                    list((review.notes_json or {}).get("notes") or []) if review else []
                ),
            },
        }
