"""The Director reads a failing scene's prompt and has it rewritten before it is bought again.

Owner, 2026-10-11, after the cyclotron film (aa170155) stopped with «scenele 4, 5 așteaptă
decizia Proprietarului»: scene 4's clips showed faces the bible forbids, scene 5's a napkin vortex
where the plan asked for a pencil's spiral. «Nu trebuie să respingă un film, trebuie să îl refacă
până trece QC, cu imagine și video!», «Nu reface pur și simplu imaginea, trebuie verificat
promptul și corectat!» and «Deci directoarea citește promptul și după îl cere la rescriere cu
informații clare, ce să evite ca să treacă la QC!» A film is not left for quality: it is redone
until quality control passes, and only money stops it.

So, for a scene quality control refused (a clip, QC.CLIP; a still, LOCAL.STILL_GATE):

1. The Director reads the scene's package, the prompts the vendor was sent, the bible and every
   reason quality control gave, and writes a brief: what went wrong and why, what the shot must
   avoid, keep and change, and the layer to redo (`director_brief`). She writes it to the Video
   Editor as a letter, and his answer is a letter back.
2. The Video Editor rewrites that one scene's package from her brief (`rewrite_scene`); the
   compiler writes its prompts and the linter must not block them. No other scene is touched, so
   every other take still matches its prompt.
3. The motion layer keeps the picture: the movement and the camera move change, the still's words
   do not, so the approved still stays and a new clip is bought from it. The still layer rewrites
   the picture too: a new still is bought, then its motion. She chooses; after a motion rewrite
   that failed again, and after a still the gate refused, the picture is rewritten (the Owner's
   ladder). A still the Owner approved is never rewritten.
4. Her rewrite is a decision about the scene: `assembler.scene_memory` reads it as one, so the
   hold the failures left and the scene's count of paid attempts start again from it. What may be
   bought is still the Policy Kernel's, the budgets' and the film ceiling's.

An episode of the serial is composed from the series' look (`compose_serial_prompt`), not
compiled: it is not rewritten here yet, and waits as before.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.memory import agent_for_role, remember
from app.db import lock_for_write
from app.factual.models import ScriptDraft
from app.factual.sanitizer import wrap_in_inert_boundary
from app.media import prompt_lint as lint
from app.media.models import SceneTake, Storyboard, StoryboardScene
from app.models import DomainEvent
from app.services import append_event

logger = logging.getLogger("studio.scene_rewrite")

#: The Director's brief for one scene: {scene_index, layer, diagnosis, avoid, keep, change,
#: summary_ro, failures, run_id, message_id}.
BRIEF_EVENT = "media.director_scene_brief"
#: The reason a `SCENE_PROMPTS_REWRITTEN_EVENT` carries when her brief rewrote the scene.
REWRITE_REASON = "director_brief"
#: Who decided a rewrite, as `scene_memory` reads it.
DECIDED_BY = "director"
BRIEF_TASK = "director_scene_brief"
BRIEF_TEMPLATE = "director-scene-brief-v1"
REWRITE_TASK = "scene_prompt_rewrite"
REWRITE_TEMPLATE = "scene-prompt-rewrite-v1"
LAYERS: tuple[str, ...] = ("motion", "still")
MOTION, STILL = LAYERS
#: The refusals of quality control the Director answers with a rewrite.
STILL_GATE_CODE = "LOCAL.STILL_GATE"
QUALITY_CODES: tuple[str, ...] = ("QC.CLIP", STILL_GATE_CODE)
#: A motion rewrite that failed again on the same picture: the next one rewrites the picture.
MOTION_REWRITES_BEFORE_STILL = 1
#: The package fields a motion rewrite may change; the still is compiled from none of them.
MOTION_FIELDS: tuple[str, ...] = ("motion", "camera_move", "ending_frame")
#: Every field of a shot the editor writes (`prompt_agent.ShotPrompt`), but its index.
SHOT_FIELDS: tuple[str, ...] = (
    "story_purpose",
    "subject",
    "action",
    "environment",
    "camera",
    "lighting",
    "composition",
    "motion",
    "emotion",
    "background",
    "continuity",
    "ending_frame",
    "audio_intent",
    "transition",
    "avoid",
    "camera_move",
    "second_framing",
)
#: The compiled package keys that make the motion what it is (`assembler.motion_fields`).
MOTION_IDENTITY: tuple[str, ...] = (
    "motion_prompt",
    "motion_intent",
    "negative_prompt",
    "camera_move",
)
#: How many of the scene's refusals and earlier briefs she is shown, newest first.
MAX_FAILURES_SHOWN = 6
MAX_BRIEFS_SHOWN = 4
MAX_PAYLOAD_CHARS = 14000


class SceneBrief(BaseModel):
    """The Director's brief to the Video Editor for one scene quality control refused."""

    model_config = ConfigDict(extra="ignore")
    diagnosis: str = Field(min_length=1, max_length=800)
    layer: Literal["motion", "still"]
    avoid: list[str] = Field(min_length=1, max_length=8)
    keep: list[str] = Field(default_factory=list, max_length=8)
    change: list[str] = Field(min_length=1, max_length=8)
    summary_ro: str = Field(min_length=1, max_length=500)

    @field_validator("layer", mode="before")
    @classmethod
    def _lower(cls, value: Any) -> Any:
        return str(value).strip().lower() if isinstance(value, str) else value

    @field_validator("avoid", "keep", "change", mode="before")
    @classmethod
    def _items(cls, value: Any) -> Any:
        items = value if isinstance(value, list) else [value] if value else []
        cleaned = [" ".join(str(item).split())[:240] for item in items if str(item).strip()]
        return cleaned[:8]


def brief_schema(allowed: tuple[str, ...]) -> type[SceneBrief]:
    """Her brief bound to the layers this scene may be redone on."""

    class BoundBrief(SceneBrief):
        @model_validator(mode="after")
        def _allowed(self) -> BoundBrief:
            if self.layer not in allowed:
                raise ValueError(f"layer {self.layer} is not open for this scene: {allowed}")
            return self

    return BoundBrief


def shot_schema(index: int, layer: str) -> type[BaseModel]:
    """The editor's one shot, fitted to the shot schema (`prompt_agent._coerce`), and holding
    what the layer rewrites: a motion for the motion layer, the picture and its motion for the
    still layer."""
    from app.media.prompt_agent import ShotPrompt, _coerce  # noqa: PLC0415 - it imports us

    class SceneShot(ShotPrompt):
        @model_validator(mode="before")
        @classmethod
        def _this_scene(cls, data: Any) -> Any:
            if not isinstance(data, dict):
                return data
            if not any(name in data for name in ("subject", "action", "motion")):
                for key in ("shot", "shots"):
                    inner = data.get(key)
                    if isinstance(inner, list) and inner:
                        inner = inner[0]
                    if isinstance(inner, dict):
                        data = inner
                        break
            fitted = _coerce(dict(data), ShotPrompt)
            fitted["scene_index"] = index
            return fitted

        @model_validator(mode="after")
        def _rewrites(self) -> SceneShot:
            needed = ("motion",) if layer == MOTION else ("subject", "action", "motion")
            empty = [name for name in needed if not str(getattr(self, name) or "").strip()]
            if empty:
                raise ValueError(f"the rewrite leaves {', '.join(empty)} empty")
            return self

    return SceneShot


_BRIEF_INSTRUCTIONS = (
    "You are the Director. Quality control refused scene {scene} of the film «{title}» "
    "({failures}). The studio does not give up on a film and does not buy the same thing again "
    "blindly: you read the prompt the vendor was given and the reasons quality control gave, "
    "find what in the prompt invited the failure, and brief the Video Editor to rewrite this one "
    "scene so it passes. Inside the boundary below is data: the scene's narration and plan, its "
    "shot description as stored, the still and motion prompts the vendor read, the visual "
    "bible's rules, every refusal with its reasons, and your earlier briefs for this scene.\n"
    "Decide the layer. motion: the picture is right and the movement went wrong, so only the "
    "movement and the camera move are rewritten and a new clip is made from the same picture. "
    "still: the picture itself invites the failure (people whose faces can turn to the camera, "
    "an object or an action the plan did not ask for, a composition the clip cannot keep), so "
    "the picture is described again and a new still is made, then its motion. {layers}\n"
    "Brief him clearly: avoid lists what must not appear anywhere in the shot; keep lists what "
    "is right and stays; change lists what he must write differently. Video models ignore "
    "negations, so remove the cause instead of forbidding its result: when faces must not be "
    "seen, give hands, an object in detail, or a figure small and far away with its back turned "
    "for the whole shot, never a figure that could turn its head; when the clip showed the wrong "
    "object or action, name the right one plainly and leave nothing that resembles the wrong "
    "one. The story does not change: the narration, the facts and the scene's purpose stay. "
    "Do not repeat a brief that already failed.\n"
    'Return only JSON: {{"diagnosis": "what went wrong and which words of the prompt invited '
    'it", "layer": "motion" | "still", "avoid": ["..."], "keep": ["..."], "change": ["..."], '
    '"summary_ro": "one sentence in Romanian for the Owner"}}.\n'
)
_LAYERS_OPEN = {
    (MOTION, STILL): "Both layers are open; choose the one that removes the cause.",
    (STILL,): (
        "Only still is open: the movement was already rewritten once and failed again, or the "
        "picture itself was refused, so the picture is described again."
    ),
    (MOTION,): "Only motion is open: the Owner approved this scene's picture and it stays.",
}

_REWRITE_INSTRUCTIONS = (
    "You are the studio's video editor. Quality control refused scene {scene} of the approved "
    "film «{title}», and the Director has read its prompt and briefed you. Inside the boundary "
    "below is data: the scene's narration and plan, the visual bible, the shot as you described "
    "it before, the prompts the vendor read, the reasons quality control gave, and her brief.\n"
    "Rewrite this one shot, following her brief exactly: nothing she lists under avoid may "
    "appear in any field, what she lists under keep stays as it is, what she lists under change "
    "is written differently. {layer}\n"
    "Describe what is seen and what moves, plainly and positively: a generator does not read "
    "'no' or 'without', it draws the word. When the bible says people's faces must not be seen, "
    "show people only from behind, small and distant, or only their hands. Never ask for writing "
    "in the picture. Do not add facts, numbers, dates or events that are not in the narration. "
    "Choose camera_move from: static, slow push-in, slow pull-back, slow pan left, slow pan "
    "right, tilt up, tilt down, aerial drift forward, pedestal up, slow orbit. Name colours in "
    "words. Return only JSON with this shot: "
    '{{"scene_index": {scene}, "subject": "...", "action": "...", "environment": "...", '
    '"camera": "...", "camera_move": "...", "lighting": "...", "composition": "...", '
    '"motion": "...", "emotion": "...", "background": "...", "continuity": "...", '
    '"ending_frame": "...", "avoid": ["..."]}}.\n'
)
_LAYER_RULE = {
    MOTION: (
        "Only the movement is rewritten: give motion, camera_move and ending_frame anew; the "
        "picture is kept, so subject, action, environment, lighting and camera stay word for "
        "word as they were."
    ),
    STILL: (
        "The picture is described again (subject, action, environment, camera, lighting, "
        "composition) and its movement with it (motion, camera_move, ending_frame)."
    ),
}


# ------------------------------------------------------------------ what the scene says


def _payload(event: Any) -> dict[str, Any]:
    return event.payload if isinstance(getattr(event, "payload", None), dict) else {}


def _owner_still(session: Session, storyboard_id: str, scene_index: int) -> bool:
    """Whether the Owner approved a still of this scene himself (it is never rewritten)."""
    from app.media.director_qc import owner_approved_take_ids  # noqa: PLC0415 - it imports us

    his = owner_approved_take_ids(session, storyboard_id)
    if not his:
        return False
    return any(
        row.id in his
        for row in session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == scene_index,
                SceneTake.kind == "still",
                SceneTake.status == "APPROVED",
            )
        )
    )


def _local_move(session: Session, storyboard_id: str, scene_index: int) -> bool:
    """Whether the Owner chose to animate this scene locally: no paid motion is bought for it."""
    from app.media.director_qc import owner_scene_choices  # noqa: PLC0415 - it imports us
    from app.media.production_policy import LOCAL_MOVE  # noqa: PLC0415

    return owner_scene_choices(session, storyboard_id).get(scene_index) == LOCAL_MOVE


def scene_takes(session: Session, storyboard_id: str, scene_index: int) -> list[SceneTake]:
    """The scene's takes of every kind, newest first."""
    return list(
        session.scalars(
            select(SceneTake)
            .where(SceneTake.storyboard_id == storyboard_id, SceneTake.scene_number == scene_index)
            .order_by(SceneTake.created_at.desc())
        )
    )


def last_failure_code(session: Session, storyboard_id: str, scene_index: int) -> str | None:
    """The code of the scene's newest take that failed it (`assembler.take_failure`), or None.

    Only a failure newer than every take of the scene that came out right counts: a scene whose
    newest clip passed is not refused, whatever an older one said."""
    from app.media.assembler import take_failure  # noqa: PLC0415 - a large module

    for row in scene_takes(session, storyboard_id, scene_index):
        if row.status in ("PAID", "APPROVED", "SUBMITTED"):
            return None
        record = take_failure(row)
        if record is not None:
            return str(record.code or record.kind or "")
    return None


def scene_failures(session: Session, storyboard_id: str, scene_index: int) -> list[dict[str, Any]]:
    """The scene's takes quality control refused, newest first, each with its reasons: a clip's
    blocks from its clip-QC report, a still's from the gate's words."""
    from app.media.assembler import clip_qc_of  # noqa: PLC0415 - a large module

    failures: list[dict[str, Any]] = []
    for row in scene_takes(session, storyboard_id, scene_index):
        if row.status != "REJECTED" or row.failure_code not in QUALITY_CODES:
            continue
        reasons: list[str] = []
        if row.failure_code == "QC.CLIP":
            report = clip_qc_of(session, row.id) or {}
            reasons = [str(item) for item in report.get("blocks_ro") or [] if item]
        if not reasons and row.failure_detail:
            reasons = [str(row.failure_detail)]
        failures.append(
            {
                "kind": row.kind,
                "model": row.model_id,
                "at": str(row.created_at or "")[:16],
                "code": row.failure_code,
                "reasons": [" ".join(reason.split())[:400] for reason in reasons[:4]],
            }
        )
        if len(failures) >= MAX_FAILURES_SHOWN:
            break
    return failures


def earlier_briefs(session: Session, storyboard_id: str, scene_index: int) -> list[dict[str, Any]]:
    """Her briefs for this scene, oldest first, and whether each rewrote it."""
    briefs: list[dict[str, Any]] = []
    for event in session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type == BRIEF_EVENT, DomainEvent.aggregate_id == storyboard_id)
        .order_by(DomainEvent.sequence)
    ):
        payload = _payload(event)
        if payload.get("scene_index") != scene_index:
            continue
        brief = {
            "at": str(event.timestamp)[:16],
            "layer": payload.get("layer"),
            "rewritten": payload.get("rewritten"),
            "diagnosis": payload.get("diagnosis"),
            "avoid": payload.get("avoid") or [],
            "change": payload.get("change") or [],
        }
        if not payload.get("rewritten"):
            # An attempt that rewrote nothing (her brief refused, his rewrite blocked): she is
            # told why, so she does not write the same brief again (2026-10-11).
            brief["reason"] = payload.get("reason") or ""
        briefs.append(brief)
    return briefs


def open_layers(
    session: Session, storyboard_id: str, scene_index: int, *, last_code: str | None
) -> tuple[str, ...]:
    """The layers this scene may be rewritten on now: never the picture of a still he
    approved; only the picture after a still the gate refused, or once the movement was
    rewritten and failed again on the same picture (the Owner's ladder)."""
    if _owner_still(session, storyboard_id, scene_index):
        return () if last_code == STILL_GATE_CODE else (MOTION,)
    if last_code == STILL_GATE_CODE:
        return (STILL,)
    motions = 0
    for brief in earlier_briefs(session, storyboard_id, scene_index):
        if not brief.get("rewritten"):
            continue
        motions = motions + 1 if brief.get("layer") == MOTION else 0
    if motions >= MOTION_REWRITES_BEFORE_STILL:
        return (STILL,)
    return (MOTION, STILL)


def _shot_of(package: dict[str, Any]) -> dict[str, Any]:
    return {name: package.get(name) for name in SHOT_FIELDS if package.get(name) not in (None, "")}


def scene_context(engine: Engine, storyboard_id: str, scene_index: int) -> dict[str, Any] | None:
    """Everything one rewrite of one scene reads, or None when the scene is not one the studio
    rewrites (not filmed, a serial episode, a closed film, no package to rewrite)."""
    from app.agents.editorial import is_serial_film  # noqa: PLC0415 - agents import media
    from app.media.prompt_agent import _allowed_text, _film_facts  # noqa: PLC0415
    from app.media.shooting_sheet import film_is_closed  # noqa: PLC0415 - it imports us

    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None or film_is_closed(session, storyboard_id):
            return None
        script = session.get(ScriptDraft, board.script_draft_id) if board.script_draft_id else None
        if is_serial_film(board, script):
            return None
        rows = list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == storyboard_id)
                .order_by(StoryboardScene.scene_index)
            )
        )
        target = next((row for row in rows if int(row.scene_index) == scene_index), None)
        if target is None or str(target.scene_kind or "LIVE").upper() != "LIVE":
            return None
        package = dict(target.prompt_json or {})
        if not any(str(package.get(name) or "").strip() for name in ("subject", "action")):
            return None
        moves: list[str] = []
        previous_ending = ""
        for row in rows:
            if int(row.scene_index) >= scene_index:
                break
            earlier = dict(row.prompt_json or {})
            previous_ending = str(earlier.get("ending_frame") or "")
            if str(row.scene_kind or "LIVE").upper() == "LIVE" and earlier.get("camera_move"):
                moves.append(str(earlier["camera_move"]))
        facts = _film_facts(session, board)
        scene_facts: dict[str, Any] = next(
            (s for s in facts["scenes"] if int(s["scene_index"]) == scene_index), {}
        )
        last_code = last_failure_code(session, storyboard_id, scene_index)
        context = {
            "storyboard_id": storyboard_id,
            "scene_index": scene_index,
            "title": str(board.title or storyboard_id[:8]),
            "bible": dict(board.visual_bible_json or {}),
            "story": facts.get("story") or {},
            "scene": scene_facts,
            "allowed": _allowed_text(facts),
            "package": package,
            "visual_prompt": str(target.visual_prompt or ""),
            "shot_type": target.shot_type,
            "previous_moves": moves,
            "previous_ending": previous_ending,
            "failures": scene_failures(session, storyboard_id, scene_index),
            "briefs": earlier_briefs(session, storyboard_id, scene_index)[-MAX_BRIEFS_SHOWN:],
            "last_code": last_code,
            "layers": open_layers(session, storyboard_id, scene_index, last_code=last_code),
            "local_move": _local_move(session, storyboard_id, scene_index),
        }
    return context


def _data(context: dict[str, Any], **more: Any) -> str:
    """The context as the agents read it, inside the inert boundary's limits."""
    from app.media.prompt_agent import trim_payload  # noqa: PLC0415 - it imports us

    package = context["package"]
    data = {
        "film": {"title": context["title"], "story": context["story"]},
        "scene": {
            key: context["scene"].get(key)
            for key in ("scene_index", "story_purpose", "narration", "seconds", "writer_visual")
        },
        "shot_as_stored": _shot_of(package),
        "prompts_sent": {
            "still": package.get("still_prompt") or context["visual_prompt"],
            "motion": package.get("motion_prompt") or "",
        },
        "visual_bible": {
            key: context["bible"].get(key)
            for key in ("style", "world", "lighting", "continuity_rules", "avoid")
            if context["bible"].get(key)
        },
        "refusals": context["failures"],
        "earlier_briefs": context["briefs"],
        **more,
    }
    fitted, _dropped = trim_payload(data, MAX_PAYLOAD_CHARS)
    return json.dumps(fitted, ensure_ascii=False, default=str)


# ------------------------------------------------------------------ her brief


def director_brief(
    engine: Engine, registry: Any, context: dict[str, Any], correlation_id: str
) -> dict[str, Any]:
    """The Director's brief for one scene (`SceneBrief`), asked through `structured_run`.

    Returns {"brief": dict | None, "run_id", "agent_id", "reason"}: no brief when no Director is
    active or her answer did not validate twice (the scene then waits, as before)."""
    from app.agents.structured import structured_run  # noqa: PLC0415 - it imports services

    with Session(engine) as session:
        director = agent_for_role(session, "Director")
        director_id = director.id if director is not None else None
    if director_id is None or registry is None:
        return {"brief": None, "run_id": None, "agent_id": None, "reason": "Niciun Director activ."}
    layers = tuple(context["layers"])
    failures = context["failures"]
    prompt = _BRIEF_INSTRUCTIONS.format(
        scene=context["scene_index"],
        title=context["title"],
        failures=f"{len(failures)} refusal(s)" if failures else "refused",
        layers=str(context.get("layers_note") or _LAYERS_OPEN.get(layers, "")),
    ) + wrap_in_inert_boundary(_data(context, open_layers=list(layers)), "scene-brief")
    parsed, first, second = structured_run(
        engine,
        registry,
        director_id,
        BRIEF_TASK,
        prompt,
        BRIEF_TEMPLATE,
        correlation_id,
        brief_schema(layers),
        "",
        summary=(
            f"Citesc promptul scenei {context['scene_index']} din «{context['title'][:60]}» "
            "și motivele controlului; îi scriu lui Kael ce să evite."
        ),
        max_tokens=2500,
    )
    last = second or first
    if parsed is None:
        return {
            "brief": None,
            "run_id": last.get("id"),
            "agent_id": director_id,
            "reason": (
                "Brief-ul Directoarei nu a respectat forma cerută nici a doua oară "
                f"({last.get('error_detail') or last.get('status')})."
            ),
        }
    return {
        "brief": parsed.model_dump(),
        "run_id": last.get("id"),
        "agent_id": director_id,
        "reason": "",
    }


# ------------------------------------------------------------------ his rewrite


def rewritten_package(
    context: dict[str, Any], shot: BaseModel, layer: str, brief: dict[str, Any]
) -> dict[str, Any]:
    """The scene's package rewritten from the editor's shot on ``layer``, compiled as
    `write_shot_prompts` compiles it. The motion layer keeps every field the still is
    compiled from, and the still's words as stored."""
    from app.media.prompt_agent import (  # noqa: PLC0415 - it imports us
        LIVE_KIND,
        ShotPrompt,
        _coerce,
        _validated_package,
        compile_prompts,
    )
    from app.media.series_look import load_factual_look  # noqa: PLC0415

    stored = context["package"]
    new = shot.model_dump()
    merged = _shot_of(stored)
    taken = MOTION_FIELDS if layer == MOTION else tuple(f for f in SHOT_FIELDS if f != "avoid")
    for name in taken:
        value = new.get(name)
        if value not in (None, "", [], {}):
            merged[name] = value
    avoid: list[str] = []
    for item in [
        *(brief.get("avoid") or []),
        *(new.get("avoid") or []),
        *(stored.get("avoid") or []),
    ]:
        text = " ".join(str(item).split())
        if text and text.lower() not in {a.lower() for a in avoid}:
            avoid.append(text)
    merged["avoid"] = avoid[:10]
    fitted = _coerce(merged, ShotPrompt)
    fitted["scene_index"] = context["scene_index"]
    package, _notes = _validated_package(
        ShotPrompt.model_validate(fitted),
        context["scene"],
        context["bible"],
        context["allowed"],
        context["previous_ending"],
    )
    package["scene_kind"] = LIVE_KIND
    package["shot_type"] = context["shot_type"]
    compiled = compile_prompts(
        package,
        context["bible"],
        previous_moves=context["previous_moves"],
        look=load_factual_look(),
    )
    package.update(compiled)
    if layer == MOTION:
        # The picture stays the picture he or the gate approved: its words are not compiled
        # again, whatever the compiler would write today.
        for name in ("subject", "action", "environment", "camera", "lighting", "composition"):
            if name in stored:
                package[name] = stored[name]
        for name in ("still_prompt", "look_block", "shot_size"):
            if name in stored:
                package[name] = stored[name]
    return package


def _motion_changed(old: dict[str, Any], new: dict[str, Any]) -> bool:
    return any(old.get(name) != new.get(name) for name in MOTION_IDENTITY)


def _lint_blocks(context: dict[str, Any], package: dict[str, Any], visual: str) -> list[str]:
    """The linter's BLOCK findings this scene's new prompts would add (none it had before)."""

    def blocks(still: str, motion: str) -> set[str]:
        found = lint.lint_scene(
            lint.LintScene(
                scene=int(context["scene_index"]),
                kind="LIVE",
                still_prompt=still,
                motion_prompt=motion,
            ),
            bible=context["bible"],
        )
        return {item.message_ro for item in found if item.severity == lint.BLOCK}

    stored = context["package"]
    before = blocks(
        str(stored.get("still_prompt") or context["visual_prompt"]),
        str(stored.get("motion_prompt") or ""),
    )
    after = blocks(visual, str(package.get("motion_prompt") or ""))
    return sorted(after - before)


def rewrite_scene(
    engine: Engine,
    registry: Any,
    context: dict[str, Any],
    brief: dict[str, Any],
    correlation_id: str,
) -> dict[str, Any]:
    """The Video Editor's rewrite of one scene from the Director's brief, compiled, linted and
    stored on that scene only. Returns {"rewritten": bool, "layer", "reason", "run_id",
    "old_still_prompt", "still_prompt", "old_motion_prompt", "motion_prompt"}."""
    from app.agents.structured import structured_run  # noqa: PLC0415 - it imports services
    from app.media.prompt_agent import PROMPT_ROLE, prompt_lessons  # noqa: PLC0415

    index = int(context["scene_index"])
    layer = str(brief["layer"])
    outcome: dict[str, Any] = {"rewritten": False, "layer": layer, "reason": "", "run_id": None}
    with Session(engine) as session:
        editor = agent_for_role(session, PROMPT_ROLE)
        editor_id = editor.id if editor is not None else None
        lessons = prompt_lessons(session)
    if editor_id is None or registry is None:
        outcome["reason"] = "Niciun Video Editor activ."
        return outcome
    base = _REWRITE_INSTRUCTIONS.format(
        scene=index, title=context["title"], layer=_LAYER_RULE[layer]
    ) + wrap_in_inert_boundary(
        _data(context, director_brief=brief, lessons=lessons), "scene-rewrite"
    )
    stored = context["package"]
    refused: list[str] = []
    package: dict[str, Any] | None = None
    visual = context["visual_prompt"]
    for _attempt in (0, 1):
        prompt = base
        if refused:
            prompt += (
                "Your previous rewrite of this shot was refused by the studio's prompt check: "
                + "; ".join(refused)[:800]
                + ". Write it again without that.\n"
            )
        parsed, first, second = structured_run(
            engine,
            registry,
            editor_id,
            REWRITE_TASK,
            prompt,
            REWRITE_TEMPLATE,
            correlation_id,
            shot_schema(index, layer),
            "",
            summary=(
                f"Rescriu scena {index} din «{context['title'][:60]}» după brief-ul Directoarei."
            ),
            max_tokens=3000,
            temperature=0.3,
        )
        last = second or first
        outcome["run_id"] = last.get("id")
        if parsed is None:
            outcome["reason"] = (
                "Rescrierea lui Kael nu a respectat forma cerută nici a doua oară "
                f"({last.get('error_detail') or last.get('status')})."
            )
            return outcome
        candidate = rewritten_package(context, parsed, layer, brief)
        candidate_visual = (
            visual if layer == MOTION else str(candidate.get("still_prompt") or visual)
        )
        refused = _lint_blocks(context, candidate, candidate_visual)
        if not refused:
            package, visual = candidate, candidate_visual
            break
    if package is None:
        outcome["reason"] = (
            "Verificarea promptului a blocat rescrierea: " + "; ".join(refused)[:600]
        )
        return outcome
    still_changed = " ".join(visual.split()) != " ".join(context["visual_prompt"].split())
    if not still_changed and not _motion_changed(stored, package):
        outcome["reason"] = "Rescrierea a dat același prompt; nimic nou de cumpărat."
        return outcome
    layer_done = STILL if still_changed else MOTION
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT  # noqa: PLC0415
        from app.media.shooting_sheet import film_is_closed  # noqa: PLC0415 - it imports us

        if film_is_closed(session, context["storyboard_id"]):
            outcome["reason"] = "Filmul a fost închis între timp."
            return outcome
        row = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == context["storyboard_id"],
                StoryboardScene.scene_index == index,
            )
        )
        if row is None or dict(row.prompt_json or {}) != stored:
            outcome["reason"] = "Pachetul scenei s-a schimbat între timp; nu se scrie peste el."
            return outcome
        row.prompt_json = package
        row.visual_prompt = visual
        row.story_purpose = package.get("story_purpose") or row.story_purpose
        append_event(
            session,
            SCENE_PROMPTS_REWRITTEN_EVENT,
            "storyboard",
            context["storyboard_id"],
            1,
            {
                "storyboard_id": context["storyboard_id"],
                "scene_index": index,
                "reason": REWRITE_REASON,
                "decided_by": DECIDED_BY,
                "layer": layer_done,
                "brief": {key: brief.get(key) for key in ("diagnosis", "avoid", "keep", "change")},
                "old_still_prompt": context["visual_prompt"],
                "still_prompt": visual,
                "old_motion_prompt": stored.get("motion_prompt"),
                "motion_prompt": package.get("motion_prompt"),
                "old_package": stored,
                "package": package,
                "run_id": outcome["run_id"],
            },
            correlation_id,
        )
    outcome.update(
        rewritten=True,
        layer=layer_done,
        old_still_prompt=context["visual_prompt"],
        still_prompt=visual,
        old_motion_prompt=stored.get("motion_prompt"),
        motion_prompt=package.get("motion_prompt"),
    )
    return outcome


# ------------------------------------------------------------------ the ladder


def _letters(
    engine: Engine,
    context: dict[str, Any],
    asked: dict[str, Any],
    done: dict[str, Any],
    correlation_id: str,
) -> str | None:
    """Her brief as a letter to the Video Editor and his answer as a letter back, both settled:
    the studio's agents talk about the work, and nobody is asked to answer again."""
    from app.agents.messages import post_message, resolve_message  # noqa: PLC0415
    from app.media.prompt_agent import PROMPT_ROLE  # noqa: PLC0415

    brief = asked["brief"] or {}
    index = context["scene_index"]
    lines = [
        f"Scena {index} din «{context['title']}» a picat la control.",
        f"Ce a mers prost: {brief.get('diagnosis')}",
        "Evită: " + "; ".join(brief.get("avoid") or []),
        "Păstrează: " + ("; ".join(brief.get("keep") or []) or "-"),
        "Schimbă: " + "; ".join(brief.get("change") or []),
        "Refacem " + ("imaginea și apoi mișcarea." if brief.get("layer") == STILL else "mișcarea."),
    ]
    try:
        with Session(engine) as session, session.begin():
            editor = agent_for_role(session, PROMPT_ROLE)
            letter = post_message(
                session,
                intent="HANDOFF",
                subject=f"Rescrie scena {index} din «{context['title'][:80]}»",
                body={"storyboard_id": context["storyboard_id"], "scene_index": index, **brief},
                from_agent_id=asked.get("agent_id"),
                to_agent_id=editor.id if editor is not None else None,
                run_id=asked.get("run_id"),
                correlation_id=correlation_id,
                body_text="\n".join(lines),
            )
            redone = "imaginea și mișcarea" if done.get("layer") == STILL else "mișcarea"
            answer = (
                f"Am rescris scena {index} ({redone}). "
                f"Promptul nou de mișcare: {str(done.get('motion_prompt') or '')[:300]}"
                if done.get("rewritten")
                else f"Nu am putut rescrie scena {index}: {done.get('reason')}"
            )
            reply = post_message(
                session,
                intent="STATUS",
                subject=f"Re: Rescrie scena {index} din «{context['title'][:80]}»",
                body={"storyboard_id": context["storyboard_id"], "scene_index": index},
                from_agent_id=editor.id if editor is not None else None,
                to_agent_id=asked.get("agent_id"),
                run_id=done.get("run_id"),
                correlation_id=correlation_id,
                body_text=answer,
                in_reply_to=letter.id,
            )
            resolve_message(
                session,
                letter.id,
                resolution=answer,
                resolved_by=PROMPT_ROLE,
                correlation_id=correlation_id,
            )
            resolve_message(
                session,
                reply.id,
                resolution="citit",
                resolved_by="Director",
                correlation_id=correlation_id,
            )
            return str(letter.id)
    except Exception as exc:  # noqa: BLE001 - the rewrite stands; only its letters are missing
        logger.warning("scene_rewrite_letters_not_written", extra={"error": type(exc).__name__})
        return None


def _record_brief(
    engine: Engine,
    context: dict[str, Any],
    asked: dict[str, Any],
    done: dict[str, Any],
    message_id: str | None,
    correlation_id: str,
) -> None:
    brief = asked["brief"] or {}
    with Session(engine) as session, session.begin():
        append_event(
            session,
            BRIEF_EVENT,
            "storyboard",
            context["storyboard_id"],
            1,
            {
                "scene_index": context["scene_index"],
                "layer": done.get("layer") or brief.get("layer"),
                "asked_layer": brief.get("layer"),
                "rewritten": bool(done.get("rewritten")),
                "reason": done.get("reason") or "",
                "diagnosis": brief.get("diagnosis"),
                "avoid": brief.get("avoid") or [],
                "keep": brief.get("keep") or [],
                "change": brief.get("change") or [],
                "summary_ro": brief.get("summary_ro"),
                "failures": context["failures"],
                "brief_run_id": asked.get("run_id"),
                "rewrite_run_id": done.get("run_id"),
                "message_id": message_id,
            },
            correlation_id,
        )
        if asked.get("agent_id") and brief:
            # Only a brief she wrote is hers to remember; a failed attempt has no diagnosis.
            remember(
                session,
                memory_class="AGENT_OPINION",
                content=(
                    f"Scene {context['scene_index']} of “{context['title'][:80]}” failed quality "
                    f"control: {brief.get('diagnosis')} — rewrite {brief.get('layer')}, avoid "
                    + "; ".join(brief.get("avoid") or [])
                )[:2000],
                source_type="run",
                source_id=asked.get("run_id") or context["storyboard_id"],
                agent_id=asked["agent_id"],
            )


def rewrite_failed_scene(
    engine: Engine, registry: Any, storyboard_id: str, scene_index: int, correlation_id: str
) -> dict[str, Any]:
    """One rung of the ladder for one scene: her brief, his rewrite, their letters and the
    record. Returns {"scene_index", "rewritten", "layer", "reason", "summary_ro"}; never raises
    for the agents' faults (the scene then waits, as it did)."""
    outcome: dict[str, Any] = {
        "scene_index": scene_index,
        "rewritten": False,
        "layer": None,
        "reason": "",
        "summary_ro": "",
    }
    context = scene_context(engine, storyboard_id, scene_index)
    if context is None:
        outcome["reason"] = (
            "Scena nu este una pe care studioul o rescrie (card, serial, film închis)."
        )
        return outcome
    if context["last_code"] not in QUALITY_CODES:
        outcome["reason"] = "Scena nu a fost refuzată de controlul calității."
        return outcome
    if context["local_move"] and context["last_code"] != STILL_GATE_CODE:
        outcome["reason"] = "Proprietarul a ales mișcare locală pentru scenă."
        return outcome
    if not context["layers"]:
        outcome["reason"] = "Imaginea scenei este aprobată de Proprietar; nimic de rescris."
        return outcome
    return _rung(engine, registry, context, outcome, correlation_id)


def rewrite_for_redo(
    engine: Engine,
    registry: Any,
    storyboard_id: str,
    scene_index: int,
    layer: str,
    reasons: list[str],
    correlation_id: str,
) -> dict[str, Any]:
    """Before a paid redo the Director decided after the finished film failed QC: her brief
    from the report's words about the scene (``reasons``: her own and the report's), the Video
    Editor's rewrite on ``layer`` (still: the picture and its motion; motion: the movement).
    «Nu reface pur și simplu imaginea, trebuie verificat promptul și corectat!»

    Returns the outcome of a rung, with ``rewritable`` False when the scene is not one the
    studio rewrites (a card, a serial episode, a package with no plan, a still he approved):
    its redo goes on as it would have."""
    outcome: dict[str, Any] = {
        "scene_index": scene_index,
        "rewritten": False,
        "rewritable": True,
        "layer": None,
        "reason": "",
        "summary_ro": "",
    }
    context = scene_context(engine, storyboard_id, scene_index)
    if context is None or layer not in LAYERS:
        outcome["rewritable"] = False
        return outcome
    with Session(engine) as session:
        if layer == STILL and _owner_still(session, storyboard_id, scene_index):
            outcome["rewritable"] = False
            return outcome
    said = [" ".join(str(reason).split())[:400] for reason in reasons if str(reason).strip()]
    context["failures"] = [
        {"kind": "film", "code": "QC.FILM", "reasons": said[:4]},
        *context["failures"],
    ][:MAX_FAILURES_SHOWN]
    context["layers"] = (layer,)
    context["layers_note"] = (
        f"The finished film failed quality control and you decided to redo this scene's {layer}"
        f"{' and its motion' if layer == STILL else ''}: only {layer} is open."
    )
    return _rung(engine, registry, context, outcome, correlation_id)


def _rung(
    engine: Engine,
    registry: Any,
    context: dict[str, Any],
    outcome: dict[str, Any],
    correlation_id: str,
) -> dict[str, Any]:
    """Her brief, his rewrite, their letters and the record, for one scene's ``context``."""
    try:
        asked = director_brief(engine, registry, context, correlation_id)
    except Exception as exc:  # noqa: BLE001 - a fault waits; it never buys
        logger.warning("director_brief_failed", extra={"error": type(exc).__name__})
        asked = {
            "brief": None,
            "run_id": None,
            "agent_id": None,
            "reason": f"Brief-ul Directoarei nu a putut fi cerut ({type(exc).__name__}).",
        }
    if asked["brief"] is None:
        # 2026-10-11, 14:20 UTC, the cyclotron film: her brief was refused twice and nothing was
        # written, so the walk's stop read as the Owner's, `earlier_briefs` never saw the attempt
        # and the watchdog had nothing to read. A brief that failed is recorded like one that
        # did — rewritten False, with the reason — and no letter goes to the Video Editor, since
        # there is nothing to hand him.
        outcome["reason"] = str(asked["reason"])
        failed = {"rewritten": False, "layer": None, "reason": outcome["reason"], "run_id": None}
        _record_brief(engine, context, asked, failed, None, correlation_id)
        return outcome
    try:
        done = rewrite_scene(engine, registry, context, asked["brief"], correlation_id)
    except Exception as exc:  # noqa: BLE001 - a fault waits; it never buys
        logger.warning("scene_rewrite_failed", extra={"error": type(exc).__name__})
        done = {
            "rewritten": False,
            "layer": asked["brief"]["layer"],
            "reason": f"Rescrierea nu a putut fi făcută ({type(exc).__name__}).",
            "run_id": None,
        }
    message_id = _letters(engine, context, asked, done, correlation_id)
    _record_brief(engine, context, asked, done, message_id, correlation_id)
    outcome.update(
        rewritten=bool(done.get("rewritten")),
        layer=done.get("layer"),
        reason=str(done.get("reason") or ""),
        summary_ro=str(asked["brief"].get("summary_ro") or ""),
    )
    return outcome


def director_ladder(
    engine: Engine,
    registry: Any,
    storyboard_id: str,
    scenes: list[int],
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """The Director's rung for every scene of ``scenes`` that quality control refused.

    Returns {"rewritten": [scene outcomes that were rewritten], "not_rewritten": [the rest]}."""
    correlation = correlation_id or str(uuid4())
    rewritten: list[dict[str, Any]] = []
    left: list[dict[str, Any]] = []
    for index in sorted(set(int(scene) for scene in scenes)):
        outcome = rewrite_failed_scene(engine, registry, storyboard_id, index, correlation)
        (rewritten if outcome["rewritten"] else left).append(outcome)
    if rewritten or left:
        logger.info(
            "director_ladder",
            extra={
                "storyboard_id": storyboard_id,
                "rewritten": [item["scene_index"] for item in rewritten],
                "left": [item["scene_index"] for item in left],
            },
        )
    return {"rewritten": rewritten, "not_rewritten": left}


def quality_refused(engine: Engine, storyboard_id: str, scenes: list[int]) -> list[int]:
    """Of ``scenes``, those whose newest failure was quality control's (the ladder's to
    answer); the others (a vendor's refusal, an account, a lost take) wait as before."""
    with Session(engine) as session:
        return [
            index
            for index in sorted(set(int(scene) for scene in scenes))
            if last_failure_code(session, storyboard_id, index) in QUALITY_CODES
        ]
