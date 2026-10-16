"""The Director's second look at a picture quality control refused, before a redo is bought.

2026-10-12: 19.50 USD went to RunPod in one day, 11.05 USD of it on redos, and all three films
still failed quality control. The refusals behind those redos were readings — read on the
database copy: 42 stills refused by the stills gate (YuNet's face count on 1c038a99's faceless
bible, the vision model's «lettering» on the serial's ledger in f06808c9 scene 4), 3 clips by the
clip QC, 17 film scenes by the film's picture checks (f06808c9 scene 7: «a small sketched mark is
visible on the whiteboard») — and a reading can be wrong: on 2026-10-10 a night sky was read as a
band between panels (babcf272). Each refusal bought the next still or clip without anyone looking
whether it was right. The Owner, the same afternoon: «trece imaginile picate de la QC pe la
Directoare și să decidă dacă au picat corect sau nu și dacă trebuie refăcute», and, as a standing
rule, «LLM-ul este pe abonament! NU COSTĂ BANI SĂ TRECEM PE LA EI! GENERAREA DE IMAGINI ȘI
MIȘCĂRI COSTĂ!». A look costs nothing; a redo costs credits. So before a paid still re-roll, a
clip retry or her own film repair is bought for a refusal, the Director looks at the picture
herself (`second_look`), with quality control's own words, the scene's intent and the bible's
rules in front of her, and decides — verdict and severity tied together:

- OVERTURNED, severity none (the defect is not in the picture) or minor («DIRECTOAREA ACCEPTĂ
  DEFECTELE MICI!»), redo false: nothing is bought for it, the picture is used;
- CONFIRMED, severity serious, redo true: the purchase proceeds, her reason added to the redo's
  reasons. A minor defect is never CONFIRMED: it is accepted, never bought again;
- UNAVAILABLE (nobody's model sees, she has no seeing model, the answer did not validate twice,
  anything went wrong): the refusal stands, exactly as before this look existed. Never raised.

The bible's hard limits stay fail-closed (review of 2026-10-12: aa170155 scene 1, two faces
facing camera on a faceless bible, could be waved through as «minor»): when quality control's
refusal reads one — a face where the bible forbids faces, panels or a flat band (writing is
hers since 2026-10-15: only text laid over the picture or a logo is serious, and that she
says herself) — she may overturn it only by saying the defect is NOT in the picture (severity
none); a «minor» answer is refused with the rule quoted and asked again, and a second one is
CONFIRMED.

The Owner, the same day: «DAR TREBUIE SĂ ÎNȚELEAGĂ DE CE APAR DEFECTELE ȘI LA VIITOARELE
PROMPTURI SĂ SE ASIGURE CĂ NU MAI SUNT!». So every defect she names carries its ``cause`` (and,
for a clip or a film scene, the ``layer`` it comes from: the still or the motion), and her
general ``lesson`` goes to the prompt writers' lessons (`prompt_agent.record_prompt_lesson`,
provisional, for the film's own kind).

She is shown what quality control judged: a film scene's frames at the very moments it looked at
(the scene's shot, else the film's frames with the studio's caption rows cut out where a caption
is on screen, else the bought clip cut at the span's own times, else the still), told which, and
told the studio's caption on screen at each frame, so a fake subtitle the motion model painted
is the picture's own writing (f06808c9 scene 4, «Dut youn't est allivie s cogterd?»). She judges
an old take against the plan it was bought on, and her earlier looks at other pictures of the
scene are named as such.

The agents decide (the Owner: «LLM-urile pot raționa, pot lua decizii și pot hotărî!»): code
gives her the evidence and records what she decided; it does not decide for her. Her answer is
validated only for consistency, and an inconsistent answer is asked again with the reason quoted
(`agents.structured.structured_run`).

Every look writes one ``media.director_second_look`` event (UNAVAILABLE included, with why), and
what she concluded becomes her own AGENT_OPINION memory, as her look at the candidates of her
repair does (`agents.reviews.review_bought_pictures`, whose model choice and prompt style this
follows).
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.identity import clipped
from app.factual.sanitizer import wrap_in_inert_boundary
from app.media.markings import markings_note, planned_markings
from app.media.models import (
    MediaAsset,
    SceneTake,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.models import DomainEvent
from app.services import append_event

logger = logging.getLogger("studio.second_look")

#: The event every look writes, on the storyboard (the register's sentence is the events feed's).
SECOND_LOOK_EVENT = "media.director_second_look"
SECOND_LOOK_TASK = "director_second_look"
SECOND_LOOK_TEMPLATE_VERSION = "director-second-look-v2"
#: What a look can be about: a candidate still, a bought clip, a scene of a finished film.
KINDS = ("still", "shot", "film_scene")
#: Her verdicts, and the one the code gives when she could not look.
CONFIRMED, OVERTURNED, UNAVAILABLE = "CONFIRMED", "OVERTURNED", "UNAVAILABLE"
SEVERITIES = ("none", "minor", "serious")
#: Where a defect comes from, for a clip or a film scene: the picture the clip was made from,
#: or the movement.
LAYERS = ("still", "motion")
#: The most pictures one look is shown: a still is one, a shot three frames, a film scene three
#: frames and, where its caption rows were cut out, the three strips below them.
MAX_IMAGES = 6
#: The most of quality control's sentences she is shown (each cut at REFUSAL_CHARS).
MAX_REFUSALS = 12
REFUSAL_CHARS = 400
#: Her earlier looks at the same scene shown to her, newest last, so she stays consistent.
EARLIER_LOOKS_SHOWN = 3
#: Her lesson for the next prompts (`prompt_agent.record_prompt_lesson` refuses over 400).
LESSON_CHARS = 240
CAUSE_CHARS = 400
#: The data she is shown, as JSON, at most (each field is capped before; this is the last cap).
SHOWN_CHARS = 16000
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm", ".mkv", ".m4v"})
#: A string longer than any path that is only base64's alphabet is a prepared picture
#: (`picture_qc.still_image`'s output, as `director_qc.look_pictures` gives it).
_BASE64 = re.compile(r"[A-Za-z0-9+/=\s]+")
#: What the frames she is shown of a film scene were cut from (`film_scene_view`).
VIEW_SOURCES = ("SHOT", "FILM", "FILM_CROPPED", "FILM_CLEAR", "CLIP", "STILL")
#: The description of the frames written beside them, so a caller that passes only the paths
#: still has her told what she is looking at.
VIEW_FILE = "view.json"
#: A studio caption's start and end in the SRT are milliseconds and the burnt ASS script's are
#: centiseconds: a frame within this of a cue's edge is read as under it.
CAPTION_TOLERANCE_SECONDS = 0.01


# ------------------------------------------------------------------------- the hard limits
#
# The bible's hard limits (`fix_check.HARD_LIMITS`: a face where faces are forbidden, writing,
# panels): a refusal that reads one may be overturned only as «not in the picture».

HARD_LIMIT_MARK = "hard limit of the visual bible"
#: Words that deny the thing they name («no faces, but faint lettering»): left out before reading.
_NEGATED = re.compile(
    r"\b(?:no|without|fără)\s+(?:visible\s+|readable\s+|any\s+|human\s+)?"
    r"(?:faces?|fețe|feţe|people|persons?|text|writing|lettering|logos?)\b",
    re.IGNORECASE,
)
_FACE_WORDS = re.compile(
    r"YuNet|\bfe[țţ]e(?:le|lor)?\b|\bo\s+fa[țţ][ăa]\b|\bfaces\b"
    r"|\b(?:a|one|two|three|four|\d+|visible|human)\s+faces?\b"
    r"|\bfaces?\s+(?:is|are|was|were)\s+(?:visible|seen|shown)\b",
    re.IGNORECASE,
)
_PANEL_WORDS = re.compile(
    r"panou|\bpanels?\b|colaj|\bcollage\b|ecran\s+împ[ăa]r[țţ]it|split[- ]screen|triptych"
    r"|o\s+singur[ăa]\s+(?:fotografie|imagine)|\bmore than one (?:picture|image)\b"
    r"|\bsingle (?:continuous )?(?:picture|photograph)\b|band[ăa]\s+(?:plat[ăa]|goal[ăa])"
    r"|\b(?:flat|blank) band\b",
    re.IGNORECASE,
)
# Writing is no hard limit since 2026-10-15 (the Owner: «scrisul, ea trebuie să hotărască…
# dacă e în spate pe o carte, rămâne; pe termometru, rămâne; pe o foaie pe care scria,
# e normal; important e să nu fie scris pe imagine ca subtitrare sau logo-uri»): the words
# of a refusal never bind her on writing; her brief says what is serious (text laid over
# the picture, a logo) and what is the scene's own.
#: Each hard limit, as she is quoted it, and as the Owner reads it.
_HARD_RULES = {
    "faces": "no face may be seen: the visual bible forbids faces",
    "panels": "one continuous picture: no panels, collage, split screen, or flat or blank band",
}
_HARD_RO = {
    "faces": "fețe, deși biblia le interzice",
    "panels": "panouri sau o bandă plată",
}


def hard_limits(
    refusal: Iterable[Any], *, faces_forbidden: bool, markings: Sequence[str] = ()
) -> list[str]:
    """Which of the bible's hard limits quality control's words read («faces» only where the
    bible forbids faces; «panels» for panels, a collage or a flat band; «writing» for readable
    or garbled writing — unless the plan names an object that carries its own markings,
    ``markings``, when the writing is hers to judge: a thermometer's scale is the object, the
    Owner, 2026-10-13), in that order; empty when none."""
    text = _NEGATED.sub(" ", " ".join(" ".join(str(part or "").split()) for part in refusal))
    found: list[str] = []
    if faces_forbidden and _FACE_WORDS.search(text):
        found.append("faces")
    if _PANEL_WORDS.search(text):
        found.append("panels")
    return found


def _hard_rule(limits: Sequence[str], face_rule: str | None) -> str | None:
    """The hard limits read, quoted for her (the bible's own words on faces when it has them)."""
    if not limits:
        return None
    said = []
    for limit in limits:
        rule = _HARD_RULES[limit]
        if limit == "faces" and face_rule:
            rule += f' (the bible: "{_short(face_rule, 160)}")'
        said.append(f"«{rule}»")
    return "; ".join(said)


# ------------------------------------------------------------------------------ her answer


def _cut_words(limit: int) -> Callable[[Any], Any]:
    """A before-validator cutting a string at a word under ``limit`` (a rule cut mid-word is
    obeyed as written)."""

    def cut(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        said = " ".join(value.split())
        if len(said) <= limit:
            return said
        return said[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"

    return cut


_LAYER_WORDS = {
    "still": "still",
    "picture": "still",
    "image": "still",
    "imagine": "still",
    "motion": "motion",
    "movement": "motion",
    "clip": "motion",
    "mișcare": "motion",
    "miscare": "motion",
}


class SecondLook(BaseModel):
    """Her answer, validated for consistency only: what she sees is hers.

    - OVERTURNED, severity none or minor, redo false: the refusal is wrong, or the defect is
      real but small and the picture is used as it is.
    - CONFIRMED, severity serious, redo true: the defect is there and the scene is made again.
      A minor defect is never CONFIRMED (the Owner accepts small defects).
    - A defect (minor or serious) names its ``cause``; on a clip or a film scene its ``layer``.
    - On a hard limit of the bible (``hard_rule``, set on the look's own schema, `look_schema`)
      OVERTURNED is only severity none.
    """

    model_config = ConfigDict(extra="ignore")
    #: The kind looked at and the hard limit quality control's refusal reads (quoted), set on a
    #: look's own subclass (`look_schema`); the base is a still with no hard limit.
    look_kind: ClassVar[str] = "still"
    hard_rule: ClassVar[str | None] = None

    verdict: Literal["CONFIRMED", "OVERTURNED"]
    severity: Literal["none", "minor", "serious"]
    redo: bool
    reason_ro: str = Field(min_length=1, max_length=600)
    cause: str = Field(default="", max_length=CAUSE_CHARS + 1)
    lesson: str = Field(default="", max_length=LESSON_CHARS)
    layer: Literal["still", "motion"] | None = None
    _clip_reason = field_validator("reason_ro", mode="before")(clipped(600))
    _cut_cause = field_validator("cause", mode="before")(_cut_words(CAUSE_CHARS))
    _cut_lesson = field_validator("lesson", mode="before")(_cut_words(LESSON_CHARS))

    @field_validator("verdict", mode="before")
    @classmethod
    def _upper(cls, value: Any) -> Any:
        return str(value).strip().upper() if isinstance(value, str) else value

    @field_validator("severity", mode="before")
    @classmethod
    def _lower(cls, value: Any) -> Any:
        return str(value).strip().lower() if isinstance(value, str) else value

    @field_validator("cause", "lesson", mode="before")
    @classmethod
    def _text(cls, value: Any) -> Any:
        return "" if value is None else value

    @field_validator("layer", mode="before")
    @classmethod
    def _layer(cls, value: Any) -> Any:
        if value is None:
            return None
        said = str(value).strip().lower()
        if said in ("", "none", "null", "-"):
            return None
        return _LAYER_WORDS.get(said, said)

    @model_validator(mode="after")
    def _consistent(self) -> SecondLook:
        hard = type(self).hard_rule
        if self.verdict == CONFIRMED:
            if self.severity == "minor":
                if hard:
                    raise ValueError(_hard_refusal(hard))
                raise ValueError(
                    "un defect mic se acceptă și nu se reface (Proprietarul acceptă defectele "
                    "mici): spune OVERTURNED cu severity minor"
                )
            if self.severity == "none":
                raise ValueError(
                    "CONFIRMED names a serious defect: with severity none the refusal is wrong, "
                    "say OVERTURNED"
                )
            if not self.redo:
                raise ValueError(
                    "CONFIRMED means the scene is made again: redo must be true (say OVERTURNED "
                    "when the picture can be used as it is)"
                )
        else:
            if self.severity == "serious":
                raise ValueError(
                    "a serious defect cannot be OVERTURNED: say CONFIRMED with redo true, or say "
                    "the defect is minor or not there"
                )
            if self.redo:
                raise ValueError(
                    "OVERTURNED means the picture is used as it is and nothing is made again: "
                    "redo must be false"
                )
            if hard and self.severity != "none":
                raise ValueError(_hard_refusal(hard))
        if self.severity != "none" and not self.cause.strip():
            raise ValueError(
                "cause: a defect names why it appears (what in the prompt, the plan, the still "
                "or the model made it), in one sentence"
            )
        if self.severity != "none" and type(self).look_kind != "still" and self.layer is None:
            raise ValueError(
                "layer: say where the defect comes from: still (it is already in the picture "
                "the clip was made from) or motion (the movement made it)"
            )
        return self


def _hard_refusal(rule: str) -> str:
    return (
        f"quality control's refusal reads a {HARD_LIMIT_MARK} ({rule}): a trace of it is never "
        "a small defect. Say OVERTURNED with severity none only if the defect is NOT in the "
        "picture at all; if any of it is there, say CONFIRMED with severity serious and redo true"
    )


@functools.lru_cache(maxsize=64)
def look_schema(kind: str, hard_rule: str | None = None) -> type[SecondLook]:
    """Her answer's schema for one look: the kind looked at (a clip or a film scene names its
    defect's layer) and the hard limit its refusal reads, quoted in the refusal of a «minor»."""
    if kind == "still" and hard_rule is None:
        return SecondLook
    return type(  # a pydantic subclass carrying the look's two class variables
        "SecondLookFor" + "".join(part.title() for part in kind.split("_")),
        (SecondLook,),
        {"look_kind": kind, "hard_rule": hard_rule, "__module__": __name__},
    )


def _answer_spec(kind: str) -> str:
    layer = ', "layer": "still" | "motion"' if kind != "still" else ""
    return (
        'Return only JSON: {"verdict": "CONFIRMED" | "OVERTURNED", "severity": "none" | "minor" '
        '| "serious", "redo": true | false, "reason_ro": "two sentences in Romanian for the '
        "Owner: what you actually see, and why quality control's refusal is right or wrong\", "
        '"cause": "one sentence: why the defect appears (empty with severity none)", '
        '"lesson": "one general rule for the next prompts, in English, or empty"' + layer + "}\n"
    )


_WHAT = {
    "still": "the candidate still",
    "shot": "the bought clip",
    "film_scene": "the scene in the finished film",
}
_LAYOUT = {
    "still": "the still, one picture.",
    "shot": "three frames of the clip, in order: its first, middle and last frame.",
    "film_scene": (
        "frames of the scene from the finished film, in order; where exactly they were cut "
        "from was not said."
    ),
}
_NO_CAPTIONS = (
    "No caption of the studio is on {what}: any writing you see in it, a line that looks like "
    "a subtitle included, is the picture's own writing and counts."
)
_WRITING = {
    "still": _NO_CAPTIONS.format(what="a still"),
    "shot": _NO_CAPTIONS.format(what="a bought clip"),
    "film_scene": (
        "The studio burns the narration's words into a finished film as captions near the "
        "bottom; which of them was on screen at these frames is not known here. A caption of the "
        "studio repeats the narration (`scene.narration`) word for word: any other writing — "
        "lettering, numbers, signs, logos, or a line that looks like a subtitle but does not "
        "repeat the narration (a motion model can paint a fake subtitle) — is the picture's own "
        "writing and counts."
    ),
}
_UNAVAILABLE_RO = "Directoarea nu s-a putut uita la {what}: {why}. Refuzul controlului rămâne."
_WHAT_RO = {
    "still": "imaginea",
    "shot": "clipul",
    "film_scene": "scena din film",
}
_FAIL_CLOSED_RO = (
    "Refuzul controlului atinge o limită fermă a bibliei ({limits}): Directoarea a spus că "
    "defectul e mic și, întrebată din nou, nu a spus că lipsește din imagine; o limită fermă nu se "
    "acceptă ca defect mic, așa că refuzul rămâne și scena se reface."
)
#: The run's one sentence for the Owner's history, per kind.
_SUMMARY_RO = {
    "still": (
        "Mă uit eu la imaginea scenei {scene} din «{title}», refuzată de control, înainte să se "
        "cumpere alta."
    ),
    "shot": (
        "Mă uit eu la clipul scenei {scene} din «{title}», refuzat de control, înainte să se "
        "cumpere altul."
    ),
    "film_scene": (
        "Mă uit eu la scena {scene} din filmul «{title}», refuzată de control, înainte să se "
        "refacă pe bani."
    ),
}


def _instructions(
    kind: str,
    scene: int,
    title: str,
    layout: str,
    writing: str,
    hard_rule: str | None,
    markings: Sequence[str] = (),
) -> str:
    lines = [
        f"You are the Director. Quality control refused {_WHAT[kind]} of scene {scene} of the "
        f"film «{title}». Before the studio pays to make it again, you look at it yourself. "
        "Quality control's checks are measurements and a reading, and a reading can be wrong: a "
        "face counter can take a shadow, a statue, a pattern or a figure seen from behind for a "
        "face; a band reader can take a night sky or a dark wall for a band between panels; a "
        "vision model can call a texture lettering, or say a picture misses the scene when it "
        "shows it.",
        f"Attached: {layout}",
        writing,
        "Inside the boundary below is data: `refusal`, quality control's own words for this "
        "refusal; `scene`, the scene's intent (the narration spoken over it, the scriptwriter's "
        "line or the serial's beat, `plan`: the plan this picture was bought on, the film's "
        "look) and the visual bible's rules; `frames`, what each attached image is, when known; "
        "`your_earlier_looks` at this scene, each with the takes it looked at — one whose "
        "`same_picture` is false looked at ANOTHER picture of this scene: it is context, not "
        "this picture's verdict, so judge this picture on its own.",
        "Look at the picture yourself and say what you actually see. Then decide, verdict and "
        "severity together:",
        "- CONFIRMED, severity serious, redo true: the defect is there and serious, and the "
        "scene must be made again (which costs money).",
        "- OVERTURNED, severity none, redo false: the refusal is wrong, the defect is not in the "
        "picture.",
        "- OVERTURNED, severity minor, redo false: the defect is real but small (a viewer will "
        "hardly notice it) and the picture is used as it is: the Owner accepts small defects. A "
        "minor defect is never CONFIRMED and never redone.",
        "A serious defect is: the picture does not show the scene's subject or what the "
        "narration says; a face where the bible forbids faces; text laid over the picture like "
        "a subtitle or a caption, a logo or a watermark; panels, a collage, a split screen or a "
        "picture with a blank band across it; a deformed person (extra or missing limbs, a "
        "melted face); for a clip, a broken, melting or frozen picture.",
        "Writing that belongs to an object in the scene is the scene's own, not a defect (the "
        "Owner, 2026-10-15): papers or a book in the background, the page someone is writing "
        "on, a screen, a thermometer's scale. Say OVERTURNED with severity none when the scene "
        "would show it, minor when it is a small stray trace; CONFIRMED only when it is laid "
        "over the picture, is a logo, or says something the story must not.",
        "A camera move or a pace other than the plan's — a zoom where it asked for a static "
        "frame, a drift the other way, «not the same shot» — is not a defect while the scene "
        "still tells the same thing: say OVERTURNED with severity minor and the cause, so the "
        "next prompt says the move; CONFIRMED only when the move changes what the scene says. "
        "Every regeneration costs the Owner money; a refusal is worth it only for what a viewer "
        "sees and the story needs.",
    ]
    if hard_rule:
        lines.append(
            f"Quality control's refusal reads a {HARD_LIMIT_MARK}: {hard_rule}. A hard limit is "
            "never a small defect: OVERTURNED only with severity none, when the defect is NOT in "
            "the picture at all (quality control misread it); if any of it is there, CONFIRMED, "
            "severity serious, redo true."
        )
    if markings:
        # The Owner, 2026-10-13: «Nu ai cum să ai un termometru fără scris, grade, Celsius.»
        lines.append(
            markings_note(markings) + " Writing that is only such an object's own scale is no "
            "defect: say OVERTURNED with severity none when that is all the writing you see, "
            "minor when a small trace of other writing is there, and CONFIRMED only for writing "
            "elsewhere that draws the eye."
        )
    lines += [
        "- cause (required with minor or serious): one sentence, why the defect appears — what "
        "in the prompt, the plan, the still or the model made it. The Owner: understand why "
        "defects appear, so the next prompts make sure they do not.",
        "- lesson (optional): one general rule for the next prompts, in English, at most "
        f"{LESSON_CHARS} characters, so this defect does not appear again — no scene number, no "
        "film title, no id; empty when there is nothing to learn.",
    ]
    if kind != "still":
        lines.append(
            "- layer (required with minor or serious): still when the defect is already in the "
            "picture the clip was made from, motion when the movement made it."
        )
    return "\n".join(lines) + "\n" + _answer_spec(kind)


# --------------------------------------------------------------------------- the evidence


def _short(text: Any, limit: int = 300) -> str:
    words = " ".join(str(text or "").split())
    return words if len(words) <= limit else words[: limit - 1].rstrip() + "…"


def _when(text: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


#: The events that change a scene's words, and where each keeps the words in force before it.
_PROMPT_EVENTS = ("media.prompts_rewritten", "media.prompts_restored")
_WORDS_BEFORE = {
    "still_prompt": ("old_still_prompt", "replaced_still_prompt"),
    "motion_prompt": ("old_motion_prompt", "replaced_motion_prompt"),
}
_PLAN_LIMITS = {"still_prompt": 900, "motion_prompt": 500}


def _plan_as_bought(
    session: Session,
    storyboard_id: str,
    scene_index: int,
    bought: Mapping[str, Any],
    plan: dict[str, Any],
) -> None:
    """The plan the takes were bought on, in ``plan``: the words in force when each layer's
    take was bought (``bought``: still and motion, the takes' created_at), read from the scene's
    rewrites (`media.prompts_rewritten`, `media.prompts_restored`: the first one after the take
    keeps the words it replaced). A layer rewritten after its take whose earlier words were not
    recorded sets ``plan_may_be_newer`` (2026-10-12: f06808c9 scenes 3, 4 and 7 were recomposed
    at 13:45 UTC, after takes the audit then judged against the new words)."""
    moments = {layer: _when(at) for layer, at in bought.items() if at}
    if not any(moments.values()):
        return
    changes: list[tuple[datetime | None, dict[str, Any]]] = []
    for event in session.scalars(
        select(DomainEvent)
        .where(
            DomainEvent.event_type.in_(_PROMPT_EVENTS),
            DomainEvent.aggregate_id == storyboard_id,
        )
        .order_by(DomainEvent.sequence)
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        if payload.get("scene_index") == scene_index:
            changes.append((_when(event.timestamp), payload))
    for layer, key in (("still", "still_prompt"), ("motion", "motion_prompt")):
        at = moments.get(layer)
        if at is None:
            continue
        later = [payload for when, payload in changes if when is not None and when > at]
        if not later:
            continue
        words = next(
            (
                later[0][name]
                for name in _WORDS_BEFORE[key]
                if isinstance(later[0].get(name), str) and later[0][name].strip()
            ),
            None,
        )
        if words is None:
            earlier = [
                payload[key]
                for when, payload in changes
                if when is not None
                and when <= at
                and isinstance(payload.get(key), str)
                and payload[key].strip()
            ]
            words = earlier[-1] if earlier else None
        if words is None:
            plan["plan_may_be_newer"] = True
            continue
        plan[key] = _short(words, _PLAN_LIMITS[key])
        plan.setdefault("as_bought", []).append(layer)
    if plan.get("as_bought"):
        plan["note"] = (
            "the words this picture was bought on: the scene's plan was rewritten after it"
        )
    if plan.get("plan_may_be_newer"):
        plan["note"] = (
            "the scene's plan was rewritten after this picture was bought and the words it was "
            "bought on were not recorded: this plan may be newer than the picture, so judge it "
            "against the narration and the scene's purpose first"
        )


def scene_intent(
    session: Session,
    storyboard_id: str,
    scene_index: int,
    *,
    bought: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """What the scene is meant to show, as she reads it beside quality control's words.

    The narration spoken over it; the scriptwriter's own line (``scene_picture``: the script's
    ``visual_description``, else the package's ``writer_visual`` — never the compiled still
    prompt again, which is what `visual_prompt` holds since the prompt writer overwrote it,
    2026-10-12 on the database copy); for an episode of the serial the beat (the room, who is
    in frame, the action, the part and its lines); the plan (still and motion prompts, the
    camera move, the film's look) — with ``bought`` (each layer's take's created_at), the plan
    those takes were bought on (`_plan_as_bought`); and the bible (its rules, its avoid list,
    whether faces are forbidden and in which words). Reads only; a film or scene that is not
    there gives what is known."""
    from app.agents.editorial import is_serial_film  # noqa: PLC0415 - agents import media
    from app.factual.models import ScriptDraft  # noqa: PLC0415
    from app.media.prompt_lint import bible_face_rule  # noqa: PLC0415
    from app.media.stills_stage import _bible_rules  # noqa: PLC0415 - the gate's own rules

    board = session.get(Storyboard, storyboard_id) if storyboard_id else None
    if board is None:
        return {"scene_index": scene_index}
    script = session.get(ScriptDraft, board.script_draft_id) if board.script_draft_id else None
    serial = bool(is_serial_film(board, script))
    row = session.scalars(
        select(StoryboardScene).where(
            StoryboardScene.storyboard_id == storyboard_id,
            StoryboardScene.scene_index == scene_index,
        )
    ).first()
    package: dict[str, Any] = (
        dict(row.prompt_json) if row is not None and isinstance(row.prompt_json, dict) else {}
    )
    scenes = list(script.scenes_json or []) if script is not None else []
    # The writer's scene: the shot's own number, or the beat the montage cut it from.
    from app.media.montage import beat_of  # noqa: PLC0415

    number = beat_of(package).get("scene_number")
    writer_index = int(number) if isinstance(number, int) and number > 0 else scene_index
    entry: dict[str, Any] = (
        dict(scenes[writer_index - 1])
        if 1 <= writer_index <= len(scenes) and isinstance(scenes[writer_index - 1], dict)
        else {}
    )
    still_prompt = str(package.get("still_prompt") or (row.visual_prompt if row else "") or "")
    writer = str(entry.get("visual_description") or package.get("writer_visual") or "")
    if (
        not writer
        and row is not None
        and " ".join(str(row.visual_prompt or "").split()) != (" ".join(still_prompt.split()))
    ):
        writer = str(row.visual_prompt or "")
    bible = dict(board.visual_bible_json) if isinstance(board.visual_bible_json, dict) else {}
    intent: dict[str, Any] = {
        "film": str(board.title or storyboard_id[:8]).removeprefix("Storyboard: ").strip(),
        "serial": serial,
        "scene_index": scene_index,
        "scene_kind": str(row.scene_kind or "LIVE") if row is not None else None,
        "narration": _short(row.voiceover_segment if row is not None else "", 600),
        "purpose": _short(
            (row.story_purpose if row is not None else "") or entry.get("purpose") or "", 200
        ),
        "scene_picture": _short(writer, 600),
    }
    if serial:
        lines = [
            {
                "speaker": line.get("speaker"),
                "text": _short(line.get("text"), 200),
            }
            for line in entry.get("lines") or []
            if isinstance(line, dict)
        ][:6]
        intent["beat"] = {
            "part": str(entry.get("part") or ""),
            "location": str(
                package.get("location") or entry.get("location_name") or entry.get("location") or ""
            ),
            "in_frame": [
                str(person.get("name"))
                for person in package.get("in_frame") or []
                if isinstance(person, dict) and person.get("name")
            ],
            "action": _short(package.get("action"), 400),
            "lines": lines,
            "background": [str(name) for name in entry.get("background") or []][:6],
        }
    intent["plan"] = {
        "still_prompt": _short(still_prompt, 900),
        "motion_prompt": _short(package.get("motion_prompt"), 500) or None,
        "camera_move": package.get("camera_move") or None,
        "look": _short(package.get("look_block"), 400) or None,
    }
    # The plan's objects that carry their own markings (`markings.planned_markings`): writing
    # on them is hers to judge, never a hard limit (2026-10-13).
    marked = planned_markings(still_prompt, writer)
    if marked:
        intent["plan"]["planned_markings"] = list(marked)
    if bought:
        _plan_as_bought(session, storyboard_id, scene_index, bought, intent["plan"])
    avoid = bible.get("avoid")
    face_rule = bible_face_rule(bible)
    intent["bible"] = {
        "faces_forbidden": face_rule is not None,
        "rules": [_short(rule, 200) for rule in _bible_rules(bible)][:12],
        "avoid": [_short(item, 200) for item in avoid][:12]
        if isinstance(avoid, list | tuple)
        else [],
    }
    if face_rule is not None:
        intent["bible"]["face_rule"] = _short(face_rule, 200)
    return intent


def _bought_times(session: Session, take_ids: Sequence[str]) -> dict[str, str]:
    """When each layer's take among ``take_ids`` was bought (still, motion); a clip with no
    still take named stands for both (the still in use was bought on the words in force then)."""
    ids = [str(take) for take in take_ids if take]
    if not ids:
        return {}
    out: dict[str, str] = {}
    for row in session.scalars(select(SceneTake).where(SceneTake.id.in_(ids))):
        layer = "still" if row.kind == "still" else "motion" if row.kind in SHOT_KINDS else None
        if layer is not None and row.created_at and str(row.created_at) > out.get(layer, ""):
            out[layer] = str(row.created_at)
    if "motion" in out and "still" not in out:
        out["still"] = out["motion"]
    return out


#: The take kinds a clip is (`assembler.SHOT_TAKE_KINDS`).
SHOT_KINDS = ("motion", "test_shot")


def earlier_looks(
    session: Session,
    storyboard_id: str,
    scene_index: int,
    *,
    take_ids: Sequence[str] = (),
    skip_correlation: str | None = None,
) -> list[dict[str, Any]]:
    """Her earlier second looks at this scene, newest last (at most `EARLIER_LOOKS_SHOWN`),
    each with the takes it looked at and whether they are the takes of this look
    (``same_picture``): a verdict on another candidate is context, not this picture's. The
    newest look at the same picture is always among them. Looks of ``skip_correlation`` (an
    audit's own run, which asks every candidate of a scene in a row) are left out."""
    current = {str(take) for take in take_ids if take}
    found: list[dict[str, Any]] = []
    for event in session.scalars(
        select(DomainEvent)
        .where(
            DomainEvent.event_type == SECOND_LOOK_EVENT,
            DomainEvent.aggregate_id == storyboard_id,
        )
        .order_by(DomainEvent.sequence)
    ):
        if skip_correlation and event.correlation_id == skip_correlation:
            continue
        payload = event.payload if isinstance(event.payload, dict) else {}
        if payload.get("scene_index") != scene_index or payload.get("verdict") == UNAVAILABLE:
            continue
        theirs = [str(take) for take in payload.get("take_ids") or [] if take]
        found.append(
            {
                "at": event.timestamp,
                "kind": payload.get("kind"),
                "take_ids": theirs,
                "same_picture": bool(current) and set(theirs) == current,
                "refusal": [_short(text, 200) for text in payload.get("refusal") or []][:3],
                "verdict": payload.get("verdict"),
                "severity": payload.get("severity"),
                "cause": _short(payload.get("cause"), 200) or None,
                "reason_ro": _short(payload.get("reason_ro"), 400),
            }
        )
    shown = found[-EARLIER_LOOKS_SHOWN:]
    same = [look for look in found if look["same_picture"]]
    if same and not any(look["same_picture"] for look in shown):
        shown = sorted([*shown[1:], same[-1]], key=lambda look: str(look["at"]))
    return shown


# ----------------------------------------------------------------------------- the pictures


def _work_dir(work_dir: Path | None, key: str) -> Path:
    base = work_dir if work_dir is not None else Path(tempfile.gettempdir()) / "amn_second_look"
    folder = base / hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def frames_of(
    path: str | Path,
    kind: str,
    *,
    work_dir: Path | None = None,
    ffmpeg_path: str | None = None,
) -> list[str]:
    """What she is shown of one file, as local paths: a still (or a frame) as it is; a clip's
    first, middle and last frame, cut as quality control cuts them (`qc.clip_frames`, 1080 px
    PNGs). Empty when the file is not there or the frames cannot be cut (no encoder): the
    caller reads that as «not looked at», never as a pass. ``kind`` is the look's kind (still,
    shot, film_scene); what is shown follows the file, not the kind: a picture is shown as it
    is, a video as its three frames, whichever look it is for."""
    from app.media.qc import clip_frames  # noqa: PLC0415 - a large module
    from app.media.toolchain import find_ffmpeg  # noqa: PLC0415

    file = Path(path)
    if not file.is_file():
        return []
    if file.suffix.lower() not in VIDEO_SUFFIXES:
        return [str(file)]
    folder = _work_dir(work_dir, f"{kind}:{file.resolve()}")
    frames = clip_frames(find_ffmpeg(ffmpeg_path), file, folder)
    return [str(frame) for _at, _time, frame in frames]


def _file_sha256(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


_SHA256 = re.compile(r"[0-9a-f]{64}")


def _film_is_the_one_judged(film: Path, recorded: str) -> bool:
    """Whether the film on disk is the file quality control judged: its sha256 is the one the
    render recorded (``provenance_hash``). Every redo of a storyboard writes its film beside the
    others, and a film's name can be reused; a record that is not a sha256 cannot be checked."""
    said = str(recorded or "").strip().lower()
    if not _SHA256.fullmatch(said):
        return True
    return _file_sha256(film) == said


def _labelled(numbers: Sequence[int]) -> list[tuple[str, int]]:
    if len(numbers) == 3:
        return list(zip(("first", "middle", "last"), numbers, strict=True))
    return [(f"frame_{position}", number) for position, number in enumerate(numbers, start=1)]


def _seconds(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _clip_at_span(
    ffmpeg_path: str | None,
    clip: Path,
    chosen: Sequence[tuple[str, int]],
    *,
    start: float,
    fps: float,
    span: Mapping[str, Any],
    folder: Path,
) -> list[tuple[str, int, Path, dict[str, Any]]]:
    """The film's frames ``chosen`` as the bought clip gives them: the film trims the clip to its
    span from its start (`assembler._shot_command`: ``shot_seconds``), plays it ``slow_factor``
    slower where it was short, and from ``second_framing.at`` shows a closer framing of it (its
    ``crop``, scaled back to 1080x1920). So a film frame is the clip at (frame / fps − start) /
    slow seconds, framed the same way — never the clip's own last frame when the film ends the
    scene earlier. (at, film frame, path, what was cut) per frame; empty when any cannot be cut."""
    from app.media.qc import probe_media_file  # noqa: PLC0415 - a large module
    from app.media.toolchain import find_ffmpeg  # noqa: PLC0415

    ffmpeg = find_ffmpeg(ffmpeg_path)
    if not ffmpeg or not clip.is_file():
        return []
    probe = probe_media_file(clip, ffmpeg)
    if not probe.get("ok"):
        return []
    clip_fps = _seconds(probe.get("video_fps")) or fps
    length = _seconds(probe.get("video_duration_seconds")) or _seconds(
        probe.get("duration_seconds")
    )
    shot_seconds = _seconds(span.get("shot_seconds")) or max(
        0.0, (_seconds(span.get("end")) or start) - start
    )
    slow = _seconds(span.get("slow_factor")) or 1.0
    slow = slow if slow > 1.0 else 1.0
    framing = (
        span.get("second_framing") if isinstance(span.get("second_framing"), Mapping) else None
    )
    folder.mkdir(parents=True, exist_ok=True)
    out: list[tuple[str, int, Path, dict[str, Any]]] = []
    for at, number in chosen:
        within = max(0.0, number / fps - start)
        if shot_seconds > 0:
            within = min(within, max(0.0, shot_seconds - 1.0 / fps))
        moment = within / slow
        if length:
            moment = min(moment, max(0.0, length - 1.0 / clip_fps))
        chain = (
            "scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:1920,"
            "setsar=1"
        )
        closer = False
        if framing is not None and within >= float(framing.get("at") or 0.0):
            try:
                x, y, width, height = (int(value) for value in framing["crop"])
            except (KeyError, TypeError, ValueError):
                pass
            else:
                chain += f",crop={width}:{height}:{x}:{y},scale=1080:1920:flags=lanczos,setsar=1"
                closer = True
        target = folder / f"clip_{at}.png"
        try:
            result = subprocess.run(  # noqa: S603 - argument list, no shell
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-nostdin",
                    "-y",
                    "-ss",
                    f"{moment:.3f}",
                    "-i",
                    str(clip),
                    "-an",
                    "-frames:v",
                    "1",
                    "-vf",
                    chain,
                    str(target),
                ],
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if result.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
            return []
        out.append(
            (
                at,
                number,
                target,
                {
                    "clip_seconds": round(moment, 3),
                    **({"closer_framing": True} if closer else {}),
                },
            )
        )
    return out


def _captions_at(cues: Sequence[Mapping[str, Any]], moment: float) -> list[str]:
    """The studio's caption lines on screen at ``moment`` (seconds on the film's timeline)."""
    lines: list[str] = []
    for cue in cues:
        start, end = float(cue["start"]), float(cue["end"])
        if start - CAPTION_TOLERANCE_SECONDS <= moment < end + CAPTION_TOLERANCE_SECONDS:
            lines += [str(line) for line in cue.get("lines") or [] if str(line).strip()]
    return lines


def _frames_list(numbers: Sequence[int], fps: float) -> str:
    return ", ".join(f"{number} ({number / fps:.2f} s)" for number in numbers)


_VIEW_LAYOUT = {
    "SHOT": (
        "{count} frames of the scene's own shot — the picture the film is joined from, before "
        "the studio burnt its captions in — at the moments quality control judged (film frames "
        "{frames} at {fps:g} fps). `frames` says what each image is."
    ),
    "FILM": (
        "{count} frames of the scene as the finished film shows them, at the moments quality "
        "control judged (film frames {frames} at {fps:g} fps). `frames` says what each image is."
    ),
    "FILM_CLEAR": (
        "{count} frames of the scene as the finished film shows them, at the moments quality "
        "control judged (film frames {frames} at {fps:g} fps); none of the studio's captions is "
        "on screen at them, so each is the whole picture as the viewer sees it. `frames` says "
        "what each image is."
    ),
    "FILM_CROPPED": (
        "{count} frames of the scene from the finished film, at the moments quality control "
        "judged (film frames {frames} at {fps:g} fps). Where one of the studio's captions is on "
        "screen, the rows it is drawn in were cut out of the frame: the image is the picture "
        "above them (shorter than 9:16 for that reason alone: not a band, not a sign of panels), "
        "and the strip below them comes after the frames — part of the same picture, not "
        "another picture or a panel. `frames` says what each image is and which caption was cut."
    ),
    "CLIP": (
        "{count} frames cut from the bought clip at the moments the film shows it (film frames "
        "{frames} at {fps:g} fps): the film trims the clip to the scene's span{slow}{framing}, "
        "and these frames are cut the same way. The film's own frames could not be cut. "
        "`frames` says what each image is."
    ),
    "STILL": (
        "the still the scene was filmed from: neither the scene's shot, nor the film's frames, "
        "nor its clip could be cut, so this is the picture the movement started from, not the "
        "movement itself."
    ),
}
_VIEW_WRITING = {
    "SHOT": _NO_CAPTIONS.format(what="the scene's own shot"),
    "CLIP": _NO_CAPTIONS.format(what="a bought clip"),
    "STILL": _NO_CAPTIONS.format(what="a still"),
    "FILM": (
        "The studio burns the narration's words into the film as captions near the bottom; "
        "`frames` gives, for each image, the studio's caption on screen at its moment (`null`: "
        "none is). Any other writing — lettering, numbers, signs, logos, or a line that looks "
        "like a subtitle but is not the caption listed for that image (a motion model can paint "
        "a fake subtitle) — is the picture's own writing and counts."
    ),
}
_VIEW_WRITING["FILM_CLEAR"] = _VIEW_WRITING["FILM"]
_VIEW_WRITING["FILM_CROPPED"] = _VIEW_WRITING["FILM"]


def _clear(folder: Path) -> None:
    """The view's folder emptied of an earlier view of the same scene (ours alone: its name is
    the asset's and the scene's hash)."""
    for item in folder.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)


def film_scene_view(
    engine: Engine,
    media_asset_id: str,
    scene_index: int,
    *,
    work_dir: Path | None = None,
    ffmpeg_path: str | None = None,
    frame_numbers: Sequence[int] = (),
) -> tuple[list[str], dict[str, Any] | None]:
    """What quality control judged of a film scene, for a look at a film-QC finding (her REPAIR;
    `scripts/qc_audit.py`): the images (local paths) and what they are.

    The moments are quality control's own (``frame_numbers``, recorded on the scene's span),
    else the first, middle and last frame of the scene's span on the render's timeline
    (`qc.span_frame_numbers`). Tried in order (2026-10-12, f06808c9 scene 4: the first audit
    showed the bought clip's own first, middle and last frame — 0, 4 and 8 s of a clip the film
    trims to 5.9 s — while QC had judged the film's frames 415, 486 and 556):

    - SHOT: the scene's own shot beside the film, verified by its sha256
      (`picture_qc.clean_shots`), at those moments (`qc._shot_span_frames`), as QC judged it;
    - FILM: the film's frames at those moments, the film verified by its recorded sha256; a
      frame with one of the studio's captions on screen (the SRT beside the film) has the rows
      the captions draw in cut out (`picture_qc.cut_caption_rows`: the picture above them, the
      strip below after the frames) — FILM_CROPPED — and a frame with none is shown whole
      (FILM_CLEAR when no frame needed a cut; FILM when the film burns no captions);
    - CLIP: the clip take the render cut the scene from, its file still the one bought, cut at
      the span's own times (`_clip_at_span`), never at its own last frame;
    - STILL: the still take the scene was filmed from, when nothing else can be cut.

    The view: ``source``, ``layout`` and ``writing`` (what she is told), ``frames`` (each image:
    what it shows, its film frame and second, the studio's caption on screen there). Written
    beside the images (`VIEW_FILE`) so a look given only the paths reads it. ([], None) when
    nothing can be prepared: the caller reads it as «not looked at»."""
    from app.agents.vision import frames_at  # noqa: PLC0415
    from app.media.picture_qc import (  # noqa: PLC0415 - a large module
        caption_rows,
        clean_shots,
        cut_caption_rows,
        film_captions,
    )
    from app.media.qc import (  # noqa: PLC0415 - a large module
        DEFAULT_TIMELINE_FPS,
        _film_subtitles,
        _shot_span_frames,
        span_frame_numbers,
        timeline_spans,
    )
    from app.media.toolchain import find_ffmpeg  # noqa: PLC0415

    with Session(engine) as session:
        asset = session.get(MediaAsset, media_asset_id)
        job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == media_asset_id)
        )
        if asset is None or job is None:
            return [], None
        production: dict[str, Any] = (
            dict(job.production_json) if isinstance(job.production_json, dict) else {}
        )
        planned = {
            int(row.scene_index): float(row.duration_seconds or 0.0)
            for row in session.scalars(
                select(StoryboardScene).where(StoryboardScene.storyboard_id == job.storyboard_id)
            )
        }
        film = Path(str(asset.uri_or_path or ""))
        film_sha = str(asset.provenance_hash or "")
        recorded = next(
            (
                entry
                for entry in production.get("scenes") or []
                if isinstance(entry, Mapping) and entry.get("scene_index") == scene_index
            ),
            {},
        )
        takes: dict[str, tuple[str, str | None]] = {}
        for key in ("motion", "still_take"):
            entry = recorded.get(key)
            take_id = entry.get("take_id") if isinstance(entry, Mapping) else None
            row = session.get(SceneTake, take_id) if take_id else None
            if row is not None and row.path:
                takes[key] = (str(row.path), row.sha256)
    folder = _work_dir(work_dir, f"{media_asset_id}:{scene_index}")
    _clear(folder)
    timeline = production.get("timeline")
    fps = float(
        (timeline.get("fps") if isinstance(timeline, dict) else None)
        or production.get("fps")
        or DEFAULT_TIMELINE_FPS
    )
    span = next(
        (s for s in timeline_spans(production, planned) if s["scene_index"] == scene_index), None
    )
    raw_span: Mapping[str, Any] = next(
        (
            entry
            for entry in (timeline.get("spans") if isinstance(timeline, dict) else None) or []
            if isinstance(entry, Mapping) and entry.get("scene_index") == scene_index
        ),
        {},
    )
    numbers = sorted(
        {
            int(n)
            for n in frame_numbers or ()
            if isinstance(n, int | float) and not isinstance(n, bool) and n >= 0
        }
    )
    if not numbers and span is not None:
        numbers = [
            n
            for _at, n in span_frame_numbers(
                span["start"], span["end"], fps, span["dissolve_seconds"]
            )
        ]
    chosen = _labelled(numbers)
    start = float(span["start"]) if span is not None else 0.0
    film_dir = film.parent if str(film) not in ("", ".") else None

    def finish(
        source: str,
        images: list[Path],
        notes: list[dict[str, Any]],
        layout: str,
        writing: str | None = None,
    ) -> tuple[list[str], dict[str, Any]]:
        kept: list[str] = []
        for position, image in enumerate(images[:MAX_IMAGES], start=1):
            target = folder / f"image_{position:02d}{image.suffix or '.png'}"
            shutil.copyfile(image, target)
            kept.append(str(target))
        view = {
            "source": source,
            "layout": layout,
            "writing": writing or _VIEW_WRITING[source],
            "fps": fps,
            "film_frames": numbers,
            "frames": [
                {"image": position, **note}
                for position, note in enumerate(notes[: len(kept)], start=1)
            ],
        }
        try:
            (folder / VIEW_FILE).write_text(
                json.dumps({"images": kept, "view": view}, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            logger.warning("second_look_view_not_written", extra={"folder": str(folder)})
        return kept, view

    # SHOT: the scene's own shot, at QC's moments.
    if film_dir is not None and span is not None and chosen:
        shot = clean_shots(production, film_dir).get(scene_index)
        if shot is not None:
            taken = _shot_span_frames(shot, chosen, start, fps, ffmpeg_path, folder / "shot")
            if taken:
                return finish(
                    "SHOT",
                    [path for _at, _moment, path in taken],
                    [
                        {
                            "shows": "the scene's own shot at this film frame, before captions",
                            "film_frame": number,
                            "film_seconds": round(number / fps, 3),
                            "studio_caption": None,
                        }
                        for _at, number in chosen
                    ],
                    _VIEW_LAYOUT["SHOT"].format(
                        count=len(taken), frames=_frames_list(numbers, fps), fps=fps
                    ),
                )
    # FILM: the film's own frames, the caption rows cut out where a caption is on screen.
    if chosen and film.is_file() and _film_is_the_one_judged(film, film_sha):
        cut = frames_at(str(film), ffmpeg_path, numbers, folder / "film")
        if cut and all(number in cut for number in numbers):
            burned, _headline = film_captions(production)
            rows = caption_rows(production)
            cues = _film_subtitles(production, film.parent) if burned else []
            ffmpeg = find_ffmpeg(ffmpeg_path)
            pictures: list[Path] = []
            strips: list[Path] = []
            notes: list[dict[str, Any]] = []
            strip_notes: list[dict[str, Any]] = []
            any_cut = captioned_whole = False
            for at, number in chosen:
                moment = number / fps
                captions = _captions_at(cues, moment) if cues else None
                caption = " ".join(captions) if captions else None
                note: dict[str, Any] = {
                    "film_frame": number,
                    "film_seconds": round(moment, 3),
                    "studio_caption": caption if burned else None,
                }
                pieces = None
                if burned and rows is not None and (captions is None or captions):
                    pieces = cut_caption_rows(
                        ffmpeg,
                        cut[number],
                        rows,
                        folder / "film" / f"{at}_above.png",
                        folder / "film" / f"{at}_below.png",
                    )
                if pieces is not None:
                    any_cut = True
                    above, below = pieces
                    pictures.append(above)
                    strips.append(below)
                    if captions is None:
                        note["studio_caption"] = "unknown: the film's captions could not be read"
                    note["shows"] = (
                        "the film's frame above the rows where the studio's caption is drawn "
                        "(those rows were cut out)"
                    )
                    notes.append(note)
                    strip_notes.append(
                        {
                            "film_frame": number,
                            "film_seconds": round(moment, 3),
                            "shows": "the bottom strip of the same frame, below the cut-out rows",
                        }
                    )
                    continue
                pictures.append(cut[number])
                note["shows"] = "the film's whole frame as the viewer sees it"
                if burned and captions is not None and not captions:
                    note["note"] = (
                        "none of the studio's captions is on screen at this moment: any writing "
                        "in this image, a subtitle-like line included, is the picture's own"
                    )
                elif burned:
                    captioned_whole = True  # its rows could not be cut: the caption is there
                    if captions is None:
                        note["studio_caption"] = "unknown: the film's captions could not be read"
                notes.append(note)
            source = (
                "FILM_CROPPED"
                if any_cut
                else "FILM_CLEAR"
                if burned and not captioned_whole
                else "FILM"
            )
            return finish(
                source,
                [*pictures, *strips],
                [*notes, *strip_notes],
                _VIEW_LAYOUT[source].format(
                    count=len(pictures), frames=_frames_list(numbers, fps), fps=fps
                ),
                None if burned else _NO_CAPTIONS.format(what="this film (it burns none in)"),
            )
    # CLIP: the bought clip at the span's own times.
    clip = takes.get("motion")
    if clip is not None and span is not None and chosen and _file_sha256(Path(clip[0])) == clip[1]:
        taken_clip = _clip_at_span(
            ffmpeg_path,
            Path(clip[0]),
            chosen,
            start=start,
            fps=fps,
            span={**span, **dict(raw_span)},
            folder=folder / "clip",
        )
        if taken_clip:
            slow = _seconds(raw_span.get("slow_factor")) or 1.0
            framing = raw_span.get("second_framing")
            return finish(
                "CLIP",
                [path for _at, _number, path, _said in taken_clip],
                [
                    {
                        "shows": "the bought clip at the moment the film shows this frame",
                        "film_frame": number,
                        "film_seconds": round(number / fps, 3),
                        **said,
                        "studio_caption": None,
                    }
                    for _at, number, _path, said in taken_clip
                ],
                _VIEW_LAYOUT["CLIP"].format(
                    count=len(taken_clip),
                    frames=_frames_list(numbers, fps),
                    fps=fps,
                    slow=f", plays it {slow:.2f}x slower" if slow > 1.0 else "",
                    framing=(
                        f", and from {float(framing.get('at') or 0):.2f} s into the scene shows "
                        "a closer framing of the same picture"
                        if isinstance(framing, Mapping)
                        else ""
                    ),
                ),
            )
    # STILL: the picture the scene was filmed from.
    still = takes.get("still_take")
    if still is not None and _file_sha256(Path(still[0])) == still[1]:
        return finish(
            "STILL",
            [Path(still[0])],
            [{"shows": "the still the scene was filmed from", "studio_caption": None}],
            _VIEW_LAYOUT["STILL"],
        )
    return [], None


def film_scene_frames(
    engine: Engine,
    media_asset_id: str,
    scene_index: int,
    *,
    work_dir: Path | None = None,
    ffmpeg_path: str | None = None,
    frame_numbers: Sequence[int] = (),
) -> tuple[list[str], str | None]:
    """The scene's frames as quality control judged them, and where they came from (SHOT,
    FILM, FILM_CROPPED, FILM_CLEAR, CLIP, STILL): `film_scene_view` without the view. A look
    given these paths reads the view written beside them."""
    images, view = film_scene_view(
        engine,
        media_asset_id,
        scene_index,
        work_dir=work_dir,
        ffmpeg_path=ffmpeg_path,
        frame_numbers=frame_numbers,
    )
    return images, (view or {}).get("source")


def view_beside(images: Sequence[str]) -> dict[str, Any] | None:
    """The view `film_scene_view` wrote beside these very images, or None."""
    paths = [str(item) for item in images if isinstance(item, str) and 0 < len(item) < 1024]
    if not paths or len(paths) != len(images):
        return None
    record = Path(paths[0]).parent / VIEW_FILE
    try:
        data = json.loads(record.read_text(encoding="utf-8")) if record.is_file() else None
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("images") != paths:
        return None
    view = data.get("view")
    return view if isinstance(view, dict) and view.get("source") in VIEW_SOURCES else None


def _prepared(
    images: Iterable[str], kind: str, *, ffmpeg_path: str | None, work_dir: Path | None
) -> list[str]:
    """The pictures as the seeing model is sent them (base64 JPEG at 1080 px,
    `picture_qc.still_image`): a still or a frame by its path; a clip by its three frames
    (`frames_of`); a picture already prepared as it is. At most `MAX_IMAGES`."""
    from app.media.picture_qc import still_image  # noqa: PLC0415 - a large module
    from app.media.toolchain import find_ffmpeg  # noqa: PLC0415

    ffmpeg = find_ffmpeg(ffmpeg_path)
    out: list[str] = []
    for item in images:
        text = str(item or "")
        if not text:
            continue
        path = Path(text) if len(text) < 1024 else None
        if path is not None and path.is_file():
            for frame in frames_of(path, kind, work_dir=work_dir, ffmpeg_path=ffmpeg_path):
                picture = still_image(ffmpeg, frame)
                if picture:
                    out.append(picture)
        elif len(text) > 256 and _BASE64.fullmatch(text):
            out.append(text)
        if len(out) >= MAX_IMAGES:
            break
    return out[:MAX_IMAGES]


# ------------------------------------------------------------------------------- the look


def _refusal(refusal: Iterable[Any]) -> list[str]:
    return [_short(text, REFUSAL_CHARS) for text in refusal if str(text or "").strip()][
        :MAX_REFUSALS
    ]


#: The keys every answer carries beyond the shared contract's five.
EXTRA_KEYS = ("cause", "lesson", "layer", "source")


def _record(
    engine: Engine,
    *,
    storyboard_id: str,
    scene_index: int,
    kind: str,
    take_ids: list[str],
    refusal: list[str],
    outcome: dict[str, Any],
    correlation_id: str,
    context: Mapping[str, Any],
) -> None:
    """One event per look; her own memory of what she concluded when she looked; and her lesson
    for the next prompts (`prompt_agent.record_prompt_lesson`, provisional: no picture has
    proven it yet; for the film's own kind). A failure to record is logged, never raised: the
    look's answer still reaches its caller."""
    director_id = context.get("director_id")
    title = str(context.get("title") or storyboard_id[:8])
    try:
        with Session(engine) as session, session.begin():
            from app.db import lock_for_write  # noqa: PLC0415

            lock_for_write(session)
            stored = False
            lesson = str(outcome.get("lesson") or "").strip()
            if (
                lesson
                and outcome["verdict"] != UNAVAILABLE
                and outcome["severity"] in ("minor", "serious")
                and not context.get("fail_closed")
            ):
                stored = _keep_lesson(session, lesson, outcome.get("run_id"), context.get("serial"))
            append_event(
                session,
                SECOND_LOOK_EVENT,
                "storyboard",
                storyboard_id,
                1,
                {
                    "storyboard_id": storyboard_id,
                    "scene_index": scene_index,
                    "kind": kind,
                    "take_ids": take_ids,
                    "refusal": refusal,
                    "verdict": outcome["verdict"],
                    "severity": outcome["severity"],
                    "redo": outcome["redo"],
                    "reason_ro": outcome["reason_ro"],
                    "run_id": outcome["run_id"],
                    "cause": outcome.get("cause") or "",
                    "lesson": lesson,
                    "lesson_stored": stored,
                    "layer": outcome.get("layer"),
                    "source": outcome.get("source"),
                    "hard_limits": list(context.get("hard_limits") or []),
                    # Only when the plan names an object with its own markings (2026-10-13):
                    # the event of a plain scene reads as it always did.
                    **(
                        {"planned_markings": list(context["planned_markings"])}
                        if context.get("planned_markings")
                        else {}
                    ),
                    "fail_closed": bool(context.get("fail_closed")),
                    "plan_as_bought": list(context.get("plan_as_bought") or []),
                    "plan_may_be_newer": bool(context.get("plan_may_be_newer")),
                },
                correlation_id,
            )
            if director_id and outcome["verdict"] != UNAVAILABLE:
                from app.agents.memory import remember  # noqa: PLC0415 - agents import media

                cause = str(outcome.get("cause") or "").strip()
                remember(
                    session,
                    memory_class="AGENT_OPINION",
                    content=(
                        f"Second look at the {kind.replace('_', ' ')} of scene {scene_index} of "
                        f"“{title}” that quality control refused: {outcome['verdict']} "
                        f"({outcome['severity']}) — {outcome['reason_ro']}"
                        + (f" Cause: {cause}" if cause else "")
                    ),
                    source_type="run",
                    source_id=outcome["run_id"],
                    agent_id=director_id,
                )
    except Exception as exc:  # noqa: BLE001 - the look's answer is returned all the same
        logger.warning("second_look_not_recorded", exc_info=exc)


def _keep_lesson(session: Session, lesson: str, run_id: Any, serial: Any) -> bool:
    """Her lesson among the prompt writers' (scope: the film's kind; "all" when it is not
    known), in a savepoint of its own: a lesson refused or failed never loses the look's event."""
    from app.media.prompt_agent import (  # noqa: PLC0415 - a large module
        SCOPE_ALL,
        SCOPE_FACTUAL,
        SCOPE_SERIAL,
        record_prompt_lesson,
    )

    scope = SCOPE_ALL if serial is None else SCOPE_SERIAL if serial else SCOPE_FACTUAL
    try:
        with session.begin_nested():
            return bool(
                record_prompt_lesson(
                    session,
                    lesson,
                    source_id=str(run_id) if run_id else None,
                    scope=scope,
                    provisional=True,
                )
            )
    except Exception as exc:  # noqa: BLE001 - the lesson is extra; the look stands
        logger.warning("second_look_lesson_not_kept", exc_info=exc)
        return False


def _unavailable(
    kind: str, why: str, run_id: str | None = None, source: str | None = None
) -> dict[str, Any]:
    """The refusal stands, as before this look existed: ``redo`` True (what quality control's
    refusal already asks for), ``severity`` none (she judged nothing). Callers read ``verdict``."""
    return {
        "verdict": UNAVAILABLE,
        "severity": "none",
        "redo": True,
        "reason_ro": _UNAVAILABLE_RO.format(what=_WHAT_RO.get(kind, "imaginea"), why=why)[:600],
        "run_id": run_id,
        "cause": "",
        "lesson": "",
        "layer": None,
        "source": source,
    }


def second_look(
    engine: Engine,
    registry: Any | None,
    *,
    storyboard_id: str,
    scene_index: int,
    kind: str,
    images: list[str],
    refusal: list[str],
    correlation_id: str,
    take_ids: Sequence[str] = (),
    ffmpeg_path: str | None = None,
    work_dir: Path | None = None,
    view: Mapping[str, Any] | None = None,
    earlier_looks_skip: str | None = None,
) -> dict[str, Any]:
    """The Director looks at a picture quality control refused, before a redo is bought for it,
    and says whether the refusal is right, how serious the defect is, whether the scene must be
    made again, and why the defect appears.

    ``kind`` is still, shot or film_scene (`KINDS`; anything else is UNAVAILABLE).
    ``images`` are local files: a still, or frames (`frames_of`, `film_scene_view`); a clip's
    file is cut into its first, middle and last frame; a picture already prepared as base64 is
    sent as it is. ``refusal`` is quality control's own words. ``view`` says what a film scene's
    images are (`film_scene_view`; read from beside the images when not given).
    ``earlier_looks_skip``: a correlation whose looks are not shown to her as earlier looks (an
    audit's own). She is asked on her seeing model (`agents.vision.seeing_model`: hers, a slot
    of hers, else the studio's seeing employee's; the run is hers whichever answers) through
    `structured_run`: an inconsistent answer is asked once more with why, and a second failure
    is UNAVAILABLE — except a second «minor» on a hard limit of the bible, which is CONFIRMED.

    Returns {verdict: CONFIRMED | OVERTURNED | UNAVAILABLE, severity: none | minor | serious,
    redo, reason_ro, run_id, cause, lesson, layer: still | motion | None, source}. CONFIRMED is
    always serious and redoes; OVERTURNED is none or minor and never redoes. UNAVAILABLE (no
    Director, no seeing model, no registry, no picture that can be prepared, a refused run, an
    answer that did not validate twice, any error) never raises and leaves the refusal standing
    (``redo`` True). Writes one ``media.director_second_look`` event in every case, and keeps
    her lesson for the next prompts. Buys nothing."""
    take_list = [str(take) for take in take_ids or ()]
    words = _refusal(refusal or [])
    context: dict[str, Any] = {"title": str(storyboard_id)[:8]}
    index = scene_index if isinstance(scene_index, int) else -1
    try:
        index = int(scene_index)
        if kind not in KINDS:
            raise ValueError(f"unknown look kind {kind!r}")
        outcome = _look(
            engine,
            registry,
            storyboard_id=storyboard_id,
            scene_index=index,
            kind=kind,
            images=list(images or []),
            refusal=words,
            correlation_id=correlation_id,
            take_ids=take_list,
            view=dict(view) if isinstance(view, Mapping) else None,
            earlier_looks_skip=earlier_looks_skip,
            ffmpeg_path=ffmpeg_path,
            work_dir=work_dir,
            context=context,
        )
    except Exception as exc:  # noqa: BLE001 - a look never stops the caller's work
        logger.warning("second_look_failed", exc_info=exc)
        outcome = _unavailable(kind, f"o eroare la privire ({type(exc).__name__})")
    _record(
        engine,
        storyboard_id=storyboard_id,
        scene_index=index,
        kind=kind,
        take_ids=take_list,
        refusal=words,
        outcome=outcome,
        correlation_id=correlation_id,
        context=context,
    )
    return outcome


def _look(
    engine: Engine,
    registry: Any | None,
    *,
    storyboard_id: str,
    scene_index: int,
    kind: str,
    images: list[str],
    refusal: list[str],
    correlation_id: str,
    take_ids: list[str],
    view: dict[str, Any] | None,
    earlier_looks_skip: str | None,
    ffmpeg_path: str | None,
    work_dir: Path | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    """The look itself; what `_record` needs beside the outcome goes into ``context`` (the
    Director's id, the film's title and kind, the hard limits read, the plan's state)."""
    from app.agents.identity import blocker_of  # noqa: PLC0415
    from app.agents.memory import agent_for_role  # noqa: PLC0415 - agents import media
    from app.agents.services import PolicyKernelError  # noqa: PLC0415
    from app.agents.structured import structured_run  # noqa: PLC0415 - it imports services
    from app.agents.vision import seeing_model  # noqa: PLC0415
    from app.media.picture_qc import LOOKERS  # noqa: PLC0415 - a large module

    if view is None and kind == "film_scene":
        view = view_beside(images)
    source = (
        str(view["source"])
        if view is not None
        else "STILL"
        if kind == "still"
        else "CLIP"
        if kind == "shot"
        else None
    )
    with Session(engine) as session:
        try:
            intent = scene_intent(
                session, storyboard_id, scene_index, bought=_bought_times(session, take_ids)
            )
            history = earlier_looks(
                session,
                storyboard_id,
                scene_index,
                take_ids=take_ids,
                skip_correlation=earlier_looks_skip,
            )
        except Exception as exc:  # noqa: BLE001 - she still looks, with what QC said
            logger.warning("second_look_intent_unread", exc_info=exc)
            intent, history = {"scene_index": scene_index}, []
        title = str(intent.get("film") or storyboard_id[:8])
        said_plan, said_bible = intent.get("plan"), intent.get("bible")
        plan: dict[str, Any] = said_plan if isinstance(said_plan, dict) else {}
        bible: dict[str, Any] = said_bible if isinstance(said_bible, dict) else {}
        marked = tuple(str(name) for name in plan.get("planned_markings") or [])
        limits = hard_limits(
            refusal, faces_forbidden=bool(bible.get("faces_forbidden")), markings=marked
        )
        context.update(
            title=title,
            serial=intent.get("serial") if "serial" in intent else None,
            plan_as_bought=list(plan.get("as_bought") or []),
            plan_may_be_newer=bool(plan.get("plan_may_be_newer")),
            hard_limits=limits,
            planned_markings=list(marked),
        )
        director = agent_for_role(session, "Director")
        if director is None:
            return _unavailable(kind, "nu există o Directoare activă", source=source)
        director_id = str(director.id)
        context["director_id"] = director_id
        model_id = seeing_model(session, director_id, *LOOKERS)
    if model_id is None:
        return _unavailable(kind, "niciun model al studioului nu vede imagini", source=source)
    if registry is None or not registry.registered_ids():
        return _unavailable(kind, "niciun furnizor de modele nu este înregistrat", source=source)
    pictures = _prepared(images, kind, ffmpeg_path=ffmpeg_path, work_dir=work_dir)
    if not pictures:
        why = "imaginile nu au putut fi pregătite (lipsește fișierul sau codorul)"
        return _unavailable(kind, why, source=source)
    rule = _hard_rule(limits, bible.get("face_rule"))
    schema = look_schema(kind, rule)
    shown: dict[str, Any] = {
        "kind": kind,
        "refused_by": {
            "still": "the stills gate",
            "shot": "the clip QC",
            "film_scene": "the film's quality control",
        }[kind],
        "refusal": refusal,
        "scene": intent,
        "frames": (view or {}).get("frames") or None,
        "your_earlier_looks": history,
    }
    if limits:
        shown["hard_limits"] = limits
    if marked:
        shown["planned_markings"] = list(marked)
    layout = str((view or {}).get("layout") or _LAYOUT[kind])
    writing = str((view or {}).get("writing") or _WRITING[kind])
    prompt = _instructions(
        kind, scene_index, title, layout, writing, rule, marked
    ) + wrap_in_inert_boundary(_fit_shown(shown), "second-look")
    try:
        parsed, first, second = structured_run(
            engine,
            registry,
            director_id,
            SECOND_LOOK_TASK,
            prompt,
            SECOND_LOOK_TEMPLATE_VERSION,
            correlation_id or str(uuid4()),
            schema,
            "",
            summary=_SUMMARY_RO[kind].format(scene=scene_index, title=title),
            max_tokens=2000,
            extra={"images": pictures},
            model_id=model_id,
        )
    except PolicyKernelError as exc:
        return _unavailable(
            kind, f"rularea a fost oprită ({_short(exc.block_reason, 200)})", source=source
        )
    last = second or first
    run_id = str(last.get("id")) if last.get("id") else None
    if parsed is None:
        if rule and HARD_LIMIT_MARK in str(last.get("refusal") or ""):
            # Fail closed on the bible's hard limits: «minor» twice is not «not there».
            context["fail_closed"] = True
            said = _loose_answer(str(last.get("output_text") or ""))
            return {
                "verdict": CONFIRMED,
                "severity": "serious",
                "redo": True,
                "reason_ro": _FAIL_CLOSED_RO.format(
                    limits=", ".join(_HARD_RO[limit] for limit in limits)
                ),
                "run_id": run_id,
                "cause": _short(said.get("cause"), CAUSE_CHARS),
                "lesson": "",
                "layer": (
                    "still"
                    if kind == "still"
                    else _LAYER_WORDS.get(str(said.get("layer") or "").strip().lower())
                ),
                "source": source,
            }
        blocker = blocker_of(str(last.get("output_text") or ""))
        if blocker is not None:
            why = f"s-a oprit: {_short(blocker.reason, 200)}"
        elif last.get("status") == "SUCCEEDED":
            why = "răspunsul ei nu a respectat forma cerută nici a doua oară"
        else:
            detail = _short(last.get("error_detail") or last.get("status"), 200)
            why = f"rularea nu a reușit ({detail})"
        return _unavailable(kind, why, run_id, source=source)
    defect = parsed.severity != "none"
    return {
        "verdict": parsed.verdict,
        "severity": parsed.severity,
        "redo": bool(parsed.redo),
        "reason_ro": parsed.reason_ro.strip(),
        "run_id": run_id,
        "cause": parsed.cause.strip() if defect else "",
        "lesson": parsed.lesson.strip() if defect else "",
        "layer": ("still" if kind == "still" else parsed.layer) if defect else None,
        "source": source,
    }


def _fit_shown(shown: dict[str, Any]) -> str:
    """The data she is shown as JSON within `SHOWN_CHARS`, kept whole: when it is longer, her
    earlier looks lose their words first, then the bible's avoid list and the plan's look, and
    only then is the text cut."""
    said = json.dumps(shown, ensure_ascii=False, default=str)
    if len(said) <= SHOWN_CHARS:
        return said
    shown = {**shown}
    shown["your_earlier_looks"] = [
        {key: look.get(key) for key in ("take_ids", "same_picture", "verdict", "severity")}
        for look in shown.get("your_earlier_looks") or []
    ]
    scene = shown.get("scene")
    if isinstance(scene, dict):
        scene = {**scene}
        if isinstance(scene.get("bible"), dict):
            scene["bible"] = {**scene["bible"], "avoid": scene["bible"].get("avoid", [])[:4]}
        if isinstance(scene.get("plan"), dict):
            scene["plan"] = {**scene["plan"], "look": None}
        shown["scene"] = scene
    return json.dumps(shown, ensure_ascii=False, default=str)


def _loose_answer(text: str) -> dict[str, Any]:
    """The first JSON object in a refused answer, unvalidated (only for what it said)."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start >= 0:
        try:
            data, _end = decoder.raw_decode(text, start)
        except ValueError:
            start = text.find("{", start + 1)
            continue
        if isinstance(data, dict):
            return data
        start = text.find("{", start + 1)
    return {}
