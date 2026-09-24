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
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.memory import agent_for_role, remember
from app.factual.editorial import SCENE_PURPOSES
from app.factual.models import FactualClaim, ScriptDraft
from app.factual.sanitizer import wrap_in_inert_boundary
from app.media.models import CharacterBible, Storyboard, StoryboardScene
from app.media.series_look import (
    PART_PURPOSES,
    SHOT_TYPES,
    load_series_look,
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


class PromptError(ValueError):
    """The prompt package could not be written; nothing was stored."""


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
    "must never appear. Vertical 9:16, watched on a phone: the subject has to stay readable. "
    "Be specific and brief — a rule that could describe any film is not a rule. Return only "
    'JSON: {"style": "...", "realism": "...", "period": "...", "world": "...", '
    '"palette": "...", "lighting": "...", "camera_language": "...", "weather": "...", '
    '"continuity_rules": ["..."], "avoid": ["..."]}.\n'
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
    "decoration; the camera (shot size, angle, lens character, movement — and movement only "
    "when the story needs it); the lighting, with direction, quality and colour; the "
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
    "place. Return only JSON: "
    '{"shots": [{"scene_index": 1, "story_purpose": "HOOK", "subject": "...", '
    '"action": "...", "environment": "...", "camera": "...", "lighting": "...", '
    '"composition": "...", "motion": "...", "emotion": "...", "background": "...", '
    '"continuity": "...", "ending_frame": "...", "audio_intent": "...", '
    '"transition": "...", "avoid": ["..."]}]}.\n'
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
    """The description with every clause that asks for writing in the picture removed."""
    parts = re.split(r"(?<=[.!?])\s+|\s*;\s*", str(text or ""))
    kept = [part for part in parts if part.strip() and not _TEXT_REQUEST.search(part)]
    return " ".join(" ".join(kept).split())


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
    for its formatting.
    """
    fitted: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        if name not in data:
            continue
        value = data[name]
        limit = _max_length(field)
        if field.annotation is str:
            text = " ".join(_flatten(value).split())
            fitted[name] = text[:limit] if limit else text
        elif field.annotation == list[str]:
            items = value if isinstance(value, list) else [value]
            cleaned = [" ".join(_flatten(item).split()) for item in items]
            cleaned = [item for item in cleaned if item]
            fitted[name] = cleaned[:limit] if limit else cleaned
        else:
            fitted[name] = value
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


def _parse_shot_pack(text: str) -> ShotPack | None:
    """Every shot that can be placed, fitted to the schema; a broken shot costs only itself."""
    from pydantic import ValidationError  # noqa: PLC0415

    data = _first_object(text, ("shots",))
    if data is None:
        return None
    shots: list[ShotPrompt] = []
    for raw in data.get("shots") or []:
        if not isinstance(raw, dict):
            continue
        try:
            shots.append(ShotPrompt.model_validate(_coerce(raw, ShotPrompt)))
        except ValidationError:
            continue
    return ShotPack(shots=shots[:60]) if shots else None


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
        payload = json.dumps(facts, ensure_ascii=False, default=str)[:12000]
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
    theirs = [str(item)[:120] for item in raw] if isinstance(raw, list) else []
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
) -> dict[str, Any]:
    """Write the full prompt package for every shot of an approved film.

    The package is identical in both environments: the environment decides which model is
    bought, never how well the shot is described. `visual_prompt` is rewritten from the
    package, so the render, the costing and quality control need to know nothing about this.
    """
    from app.factual.story_review import story_gate  # noqa: PLC0415

    correlation = correlation_id or str(uuid4())
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise PromptError(f"Storyboard {storyboard_id} not found")
        # Describing the shots is the last step before money, so it is where the story gate
        # is enforced: a film whose story nobody judged does not get described, and one the
        # review sent back waits for the rewrite.
        passed, why = story_gate(session, board.script_draft_id)
        if not passed:
            raise PromptError(why)
        need_bible = not board.visual_bible_json
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

    packs: dict[int, ShotPrompt] = {}
    run_id = None
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
        payload = json.dumps(data, ensure_ascii=False, default=str)[:16000]
        result = _run(
            engine,
            registry,
            editor_id,
            "shot_prompts",
            instructions + wrap_in_inert_boundary(payload, "approved-film"),
            template,
            correlation,
            f"Scriu prompturile pentru {len(facts['scenes'])} cadre.",
            7000,
        )
        if result is not None:
            run_id = result["id"]
            parsed = _parse_shot_pack(result.get("output_text") or "")
            if parsed is not None:
                packs = {shot.scene_index: shot for shot in parsed.shots}

    allowed = _allowed_text(facts)
    written: list[dict[str, Any]] = []
    refused: list[str] = []
    previous_ending = ""
    with Session(engine) as session, session.begin():
        scenes = list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == storyboard_id)
                .order_by(StoryboardScene.scene_index)
            )
        )
        facts_by_index = {int(s["scene_index"]): s for s in facts["scenes"]}
        for scene in scenes:
            scene_facts = facts_by_index.get(scene.scene_index, {})
            shot = packs.get(scene.scene_index)
            package, notes = _validated_package(shot, scene_facts, bible, allowed, previous_ending)
            refused.extend(f"cadrul {scene.scene_index}: {note}" for note in notes)
            if serial:
                package = _serial_package(package, shot, scene_facts, look)
                scene.shot_type = SHOT_TYPES[package["shot_size"]]
                composed = compose_serial_prompt(package, look)
            else:
                composed = compose_prompt(package, bible)
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
            },
            correlation,
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
        "motion": (shot.motion if shot else "") or "slow, natural movement within the frame",
        "emotion": (shot.emotion if shot else ""),
        "background": (shot.background if shot else ""),
        "continuity": (shot.continuity if shot else "") or previous_ending,
        "ending_frame": (shot.ending_frame if shot else ""),
        "audio_intent": (shot.audio_intent if shot else "narration dominates"),
        "transition": (shot.transition if shot else "dissolve into the next shot"),
        "avoid": _avoid_list(shot.avoid if shot else None),
        "characters": scene.get("characters") or [],
    }
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
    # Said in the bible's order: the whole face, then the clothes.
    return _fit(name + ", ".join(part for part in face + outfit if part in kept), limit)


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


def compose_serial_prompt(package: dict[str, Any], look: dict[str, Any]) -> str:
    """The text the model receives for a serial shot, the series' look first, word for word.

    Then the room, the camera, the people in frame (each as their bible describes them) and
    the action; then, while there is room, the expression, the background, the continuity and
    the exclusions. The people are given less of their description, and then the action less
    of its words, until the prompt fits the look's cap: the look and the room never shrink.
    """
    cap = int(look.get("max_prompt_chars") or 900)
    camera = " ".join(str(package.get("camera") or "").split()).rstrip(". ")
    head = [
        str(look.get("block") or "").strip(),
        f"Location: {package['location']}." if package.get("location") else "",
        f"Camera: {camera}." if camera else "",
    ]
    people = [c for c in package.get("in_frame") or [] if isinstance(c, dict)]
    action = " ".join(str(package.get("action") or "").split())
    if action and not action.endswith("."):
        action += "."

    def build(per_person: int, action_text: str) -> str:
        who = "; ".join(_identity(c, per_person) for c in people)
        parts = [
            *head,
            f"In frame, facing the viewer: {who}." if who else "",
            f"Action: {action_text}" if action_text else "",
        ]
        return " ".join(part for part in parts if part)

    per = 220 if len(people) <= 1 else 130 if len(people) == 2 else 90
    text = build(per, action)
    while len(text) > cap and per > 45:
        per -= 10
        text = build(per, action)
    if len(text) > cap and action:
        room = len(action) - (len(text) - cap)
        text = build(per, _fit(action, room - 1) + "." if room > 20 else "")
    text = _fit(text, cap)
    for label, value in (
        ("Expression", package.get("emotion")),
        ("Background", package.get("background")),
        ("Continuity", package.get("continuity")),
        ("Avoid", ", ".join(str(a) for a in (package.get("avoid") or [])[:6])),
    ):
        said = " ".join(str(value or "").split()).rstrip(". ")
        if not said:
            continue
        candidate = f"{text} {label}: {said}."
        if len(candidate) <= cap:
            text = candidate
    return text


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
    text = " ".join(text.split())
    return text[:MAX_PROMPT_CHARS]


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
