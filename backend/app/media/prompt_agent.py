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

from app.agents.identity import parse_structured
from app.agents.memory import agent_for_role, remember
from app.factual.editorial import SCENE_PURPOSES
from app.factual.models import FactualClaim, ScriptDraft
from app.factual.sanitizer import wrap_in_inert_boundary
from app.media.models import CharacterBible, Storyboard, StoryboardScene
from app.services import append_event, utc_now

logger = logging.getLogger("studio.prompt_agent")

#: The role that owns the studio's pictures. The same steward who reads the vendors' pages
#: about video models writes the instructions those models are given.
PROMPT_ROLE = "VideoEditor"
BIBLE_TEMPLATE = "visual-bible-v1"
SHOTS_TEMPLATE = "shot-prompts-v1"

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
    "stronger, the picture shows cloud, wind, water and a reaction, not a caption. Do not "
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


# ------------------------------------------------------------------ what the film is


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
    return {
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
                "writer_visual": scene.visual_prompt,
                "shot_type": scene.shot_type,
                "claims": [claims.get(cid, "") for cid in (scene.claim_ids_json or [])],
                "characters": [
                    {
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
            parsed = parse_structured(result.get("output_text") or "", VisualBible)
            bible = parsed if isinstance(parsed, VisualBible) else None

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
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise PromptError(f"Storyboard {storyboard_id} not found")
        if not board.visual_bible_json:
            need_bible = True
        else:
            need_bible = False
        facts = _film_facts(session, board)
        editor = agent_for_role(session, PROMPT_ROLE)
        editor_id = editor.id if editor else None
        lessons = prompt_lessons(session)
    if need_bible:
        build_visual_bible(engine, registry, storyboard_id, correlation)
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        bible = dict((board.visual_bible_json or {}) if board else {})

    packs: dict[int, ShotPrompt] = {}
    run_id = None
    if editor_id is not None and registry is not None:
        payload = json.dumps(
            {"visual_bible": bible, "film": facts, "lessons": lessons},
            ensure_ascii=False,
            default=str,
        )[:16000]
        result = _run(
            engine,
            registry,
            editor_id,
            "shot_prompts",
            _SHOTS_INSTRUCTIONS + wrap_in_inert_boundary(payload, "approved-film"),
            SHOTS_TEMPLATE,
            correlation,
            f"Scriu prompturile pentru {len(facts['scenes'])} cadre.",
            7000,
        )
        if result is not None:
            run_id = result["id"]
            parsed = parse_structured(result.get("output_text") or "", ShotPack)
            if isinstance(parsed, ShotPack):
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
    for field in REQUIRED_SHOT_FIELDS:
        if not str(package.get(field) or "").strip():
            package[field] = str(scene.get("writer_visual") or bible.get("style") or "")
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


def compose_prompt(package: dict[str, Any], bible: dict[str, Any]) -> str:
    """The text the video model actually receives, in the order a model reads best.

    Subject and action first, because that is the shot; then the world, the camera, the light;
    then what must match the shot before it; and the exclusions last. Trimmed to a length
    that keeps the important half readable — a thousand meaningless words teach nothing.
    """
    characters = package.get("characters") or []
    who = "; ".join(
        f"{c.get('name')}: {c.get('face_hair')}, wearing {c.get('outfit')}"
        for c in characters
        if isinstance(c, dict)
    )
    parts = [
        str(package.get("subject") or "").strip(),
        str(package.get("action") or "").strip(),
        f"Character: {who}." if who else "",
        f"Environment: {package.get('environment')}." if package.get("environment") else "",
        f"Camera: {package.get('camera')}." if package.get("camera") else "",
        f"Lighting: {package.get('lighting')}." if package.get("lighting") else "",
        f"Composition: {package.get('composition')}." if package.get("composition") else "",
        f"Motion: {package.get('motion')}." if package.get("motion") else "",
        f"Emotion: {package.get('emotion')}." if package.get("emotion") else "",
        f"Background: {package.get('background')}." if package.get("background") else "",
        f"Style: {bible.get('style')}, {bible.get('realism')}." if bible.get("style") else "",
        f"Palette: {bible.get('palette')}." if bible.get("palette") else "",
        f"Continuity: {package.get('continuity')}." if package.get("continuity") else "",
        f"Avoid: {', '.join(str(a) for a in (package.get('avoid') or [])[:6])}.",
    ]
    text = " ".join(part for part in parts if part)
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
            },
        }
