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
5. Before anything is bought on his words, she reviews them against the findings
   (`review_rewrite`, 2026-10-12). Owner, on film 1c038a99's scene 5 redone five times: «Dacă se
   reface ceva, trebuie să ne asigurăm că promptul de regenerare este impecabil. Adică, tratează
   problema? ... Nu ai cum să faci de 5 ori aceeași greșeală!» That day her brief fixated three
   rounds on a fixed compiler sentence, his rewrite came back with an empty sentence diff, and
   the redo was bought every time: the only guard was the words being identical. Now a finding
   is treated only when the new prompt changes the words that invited it or names in their
   place what the scene asks for; a rewrite that misses any finding is not stored and nothing is
   bought on it, and a rewrite nobody could review is not stored either. The next brief is shown
   why (`earlier_briefs`), so the same diagnosis is not written again.
6. A rewrite her review refused is answered in the same rung, with her words (2026-10-12,
   16:45, f06808c9 scenes 3, 4 and 7: the motion rewrites were refused again and again —
   «Rescrierea nu tratează constatarea: …promptul de mișcare păstrează…» — and the next round
   asked the same brief, so the loop read nothing from the refusal). The Owner: «trebuie să îl
   citească, să înțeleagă ce a fost greșit și să îl refacă. DAR SĂ REFACĂ CE A FOST GREȘIT».
   Her review says, for every finding it leaves untreated, why (`FindingReview.why_not`), and
   the Video Editor rewrites once more with exactly those words (`REWRITES_PER_RUNG`); only a
   second miss stores nothing. Her review also says what in the old words invited the defect
   (`cause`) and a general rule for every future prompt (`lesson`): a rewrite she passes
   records the lesson studio-wide (`learn_from_review`, unless the studio already says it),
   and every later brief reads the studio's lessons and, for the scene, the earlier briefs with
   their reviews' causes, why_not and lessons — «la viitoarele prompturi să se asigure că nu
   mai sunt».

An episode of the serial is composed from the series' look (`compose_serial_prompt`), not
compiled, and until 2026-10-12 it was not rewritten here: its stale words were said again with
today's composer and, when the words were already today's, the same words were bought again
with another seed for ANY refusal (f06808c9 scene 4: «two women facing each other across the
ledger instead of a medium close-up single on Nadia», the same picture asked again). Now a
technical refusal of the still gate (panels, blur, a degenerate picture, an unmeasured one) is
still answered with another picture on the same words, and a content refusal (the gate's «nu
arată ce cere scena», readable text, a face, the bible, the look; a clip QC block; the film
QC's findings) goes the same way as a factual scene — her brief, his rewrite, her review — with
the serial composer saying the rewritten fields again (`serial_rewritten_package`).
"""

from __future__ import annotations

import json
import logging
import re
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
#: summary_ro, failures, run_id, message_id}, and how her review of the rewrite ended
#: (review_verdict, cause, lesson, review_findings, review_attempts; `_record_brief`).
BRIEF_EVENT = "media.director_scene_brief"
#: The reason a `SCENE_PROMPTS_REWRITTEN_EVENT` carries when her brief rewrote the scene.
REWRITE_REASON = "director_brief"
#: Who decided a rewrite, as `scene_memory` reads it.
DECIDED_BY = "director"
BRIEF_TASK = "director_scene_brief"
BRIEF_TEMPLATE = "director-scene-brief-v1"
REWRITE_TASK = "scene_prompt_rewrite"
REWRITE_TEMPLATE = "scene-prompt-rewrite-v1"
#: Her review of his rewrite against the findings, before anything is bought on it.
REVIEW_TASK = "director_rewrite_review"
REVIEW_TEMPLATE = "director-rewrite-review-v1"
TREATS, MISSES = "TREATS", "MISSES"
#: His rewrites in one rung: the first, and one more with her review's words when it missed a
#: finding (2026-10-12, f06808c9 scenes 3, 4, 7: a refused rewrite ended the rung, and the next
#: rung asked the same brief again).
REWRITES_PER_RUNG = 2
#: A lesson her review writes is kept for every future prompt only when it is a rule, not a note
#: on one scene: at most this long, and new — an existing lesson that already says this share of
#: its words means the studio knows it (`lesson_overlap`).
LESSON_MAX_CHARS = 240
LESSON_OVERLAP = 0.6
LESSONS_COMPARED = 40
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
#: The package fields the serial composer reads from a rewrite (`prompt_agent.compose_serial_prompt`
#: says the first moment of ``action``, then ``emotion``, ``background`` and ``continuity``;
#: `compose_serial_motion` says ``camera_move``, the whole ``action``, ``ending_frame`` and the
#: feeling). The still layer may change all of them; the motion layer only what the still is
#: not composed from — its feeling goes to ``motion_emotion``, read by the motion alone.
SERIAL_STILL_FIELDS: tuple[str, ...] = (
    "action",
    "emotion",
    "background",
    "continuity",
    "ending_frame",
    "camera_move",
)
SERIAL_MOTION_FIELDS: tuple[str, ...] = ("camera_move", "ending_frame")
#: How many of the scene's refusals and earlier briefs she is shown, newest first.
MAX_FAILURES_SHOWN = 6
MAX_BRIEFS_SHOWN = 4
MAX_PAYLOAD_CHARS = 14000
#: Where one sentence ends and the next begins, for the diff her review reads.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


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


class FindingReview(BaseModel):
    """One finding of quality control, and whether the rewrite treats it."""

    model_config = ConfigDict(extra="ignore")
    finding: str = Field(min_length=1, max_length=400)
    treated: bool
    #: The new sentence that treats it; empty for a finding left untreated.
    by: str = Field(default="", max_length=500)
    #: For a finding left untreated, why: what in the rewritten prompts still invites it, or
    #: what is missing. The Video Editor's second rewrite is given exactly these words
    #: (2026-10-12, f06808c9 scenes 3, 4, 7: a refusal nobody explained was asked again).
    why_not: str = Field(default="", max_length=400)

    @field_validator("by", "why_not", mode="before")
    @classmethod
    def _text(cls, value: Any) -> Any:
        return " ".join(str(value).split()) if value is not None else ""


class RewriteReview(BaseModel):
    """The Director's review of the Video Editor's rewrite against the findings.

    A finding is treated only when the new prompt changes the words that invited it or names,
    in their place, what the scene asks for; the verdict is MISSES while any finding is not,
    and every untreated finding says why (``why_not``). ``cause`` is what in the old words
    invited the defect, ``lesson`` the general rule that keeps it out of every future prompt
    (Owner, 2026-10-12: «trebuie să înțeleagă de ce apar defectele și la viitoarele prompturi
    să se asigure că nu mai sunt»)."""

    model_config = ConfigDict(extra="ignore")
    verdict: Literal["TREATS", "MISSES"]
    findings: list[FindingReview] = Field(min_length=1, max_length=12)
    reason_ro: str = Field(min_length=1, max_length=500)
    cause: str = Field(min_length=1, max_length=400)
    lesson: str = Field(min_length=1, max_length=LESSON_MAX_CHARS)

    @field_validator("verdict", mode="before")
    @classmethod
    def _upper(cls, value: Any) -> Any:
        return str(value).strip().upper() if isinstance(value, str) else value

    @field_validator("cause", "lesson", mode="before")
    @classmethod
    def _said(cls, value: Any) -> Any:
        return " ".join(str(value).split()) if isinstance(value, str) else value

    @model_validator(mode="after")
    def _consistent(self) -> RewriteReview:
        untreated = [item for item in self.findings if not item.treated]
        if untreated and self.verdict == TREATS:
            raise ValueError(
                "a review that leaves a finding untreated does not say TREATS: "
                + "; ".join(item.finding[:80] for item in untreated[:3])
            )
        if not untreated and self.verdict == MISSES:
            raise ValueError("a review that finds every finding treated does not say MISSES")
        unnamed = [item for item in self.findings if item.treated and not item.by.strip()]
        if unnamed:
            raise ValueError(
                "a treated finding must quote the new sentence that treats it: "
                + "; ".join(item.finding[:80] for item in unnamed[:3])
            )
        unexplained = [item for item in untreated if not item.why_not.strip()]
        if unexplained:
            raise ValueError(
                "an untreated finding must say why it is not treated (why_not): "
                + "; ".join(item.finding[:80] for item in unexplained[:3])
            )
        return self


def shot_schema(index: int, layer: str, *, serial: bool = False) -> type[BaseModel]:
    """The editor's one shot, fitted to the shot schema (`prompt_agent._coerce`), and holding
    what the layer rewrites: a motion for the motion layer, the picture and its motion for the
    still layer. A serial shot is composed from fewer fields (`SERIAL_STILL_FIELDS`,
    `SERIAL_MOTION_FIELDS`): its still layer must give the action, its motion layer a camera
    move, an ending frame or a feeling."""
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
            if serial:
                needed = ("action",) if layer == STILL else ()
                moved = ("camera_move", "ending_frame", "emotion")
                if layer == MOTION and not any(str(getattr(self, n) or "").strip() for n in moved):
                    raise ValueError(f"the rewrite leaves {', '.join(moved)} empty")
            else:
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
    "bible's rules, every refusal with its reasons, your earlier briefs for this scene with "
    "your reviews of their rewrites (the verdict, the cause of the defect, why a finding was "
    "not treated, the lesson), and the studio's lessons about writing prompts (lessons).\n"
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
    # 2026-10-12, 16:45, f06808c9 scenes 3, 4, 7: her reviews refused the rewrites again and
    # again, and the next brief asked the same thing — nothing read the refusal.
    "Read the earlier briefs and the reviews of their rewrites: a diagnosis or a change that "
    "was refused or failed is not repeated; follow the studio's lessons. Where a review says "
    "why a finding was not treated (why_not) or which words caused it (cause), your brief "
    "removes exactly that.\n"
    # 2026-10-12, film 1c038a99 scene 5: three briefs in a row diagnosed a fixed compiler
    # sentence the refusal never mentioned and invented a face QC never reported, while the
    # refusal («rough bare-rock tunnel with sparks, not the metallic detector cavern») went
    # unanswered and the redo was bought five times.
    "Diagnose only what the refusal names; never invent a fault the refusal does not describe. "
    "If an earlier brief for this scene made the same diagnosis and the scene failed the same "
    "way after it, that diagnosis was wrong: find another cause and change the approach (what "
    "is in frame and where, what is named first, the shot's size), not the words' tone.\n"
    'Return only JSON: {{"diagnosis": "what went wrong and which words of the prompt invited '
    'it", "layer": "motion" | "still", "avoid": ["..."], "keep": ["..."], "change": ["..."], '
    '"summary_ro": "one sentence in Romanian for the Owner"}}.\n'
)
#: Added to her brief for a shot of the office serial (f06808c9 scene 4, 2026-10-12: the still
#: showed two women face to face where the plan asked a single on Nadia; the action named both
#: women's first moments, and nothing in the brief could say who stands where).
_SERIAL_BRIEF_NOTE = (
    "This scene is a shot of the office serial. The studio composes its picture itself from "
    "the FIRST moment of the action, the people listed in in_frame (as their bibles describe "
    "them) and the shot's fixed framing for its size (serial_shot in the data), and its clip "
    "from camera_move, the whole action and ending_frame; the series' look and the room are "
    "fixed. So your brief must say who is in the picture and where — who is at the frame's "
    "edge or off camera — what the first moment shows, and what the clip ends on.\n"
)

_REVIEW_INSTRUCTIONS = (
    "You are the Director. Quality control refused scene {scene} of the film «{title}», you "
    "briefed the Video Editor, and he rewrote the shot on the {layer} layer. Before the studio "
    "pays for anything on his words, you check them against the findings: a scene redone on "
    "words that do not treat the finding is the same mistake bought again. Inside the boundary "
    "below is data: the findings quality control gave, your brief (diagnosis, avoid, change), "
    "the prompts the vendor read before, the prompts as rewritten, and the sentence-level "
    "difference between them for the still and for the motion (sentences removed, sentences "
    "added).\n"
    "A finding is TREATED only if the new prompt changes the words that invited it, or names "
    "in their place what the scene asks for. A sentence added elsewhere, a longer description "
    "of the same thing, a change of tone, or a change of the other layer (the motion when the "
    "finding is about the picture) is NOT treatment. A finding about the picture's subject, "
    "its composition, who is in frame and where, or its location must be answered in the "
    "still prompt; a finding about the movement, the camera's path or the clip's ending in "
    "the motion prompt. For each finding say whether it is treated and quote the new sentence "
    "of the rewritten prompts that treats it; for a finding left untreated say why (why_not): "
    "which words of the rewritten prompts still invite it, or what they fail to name — he "
    "rewrites once more from exactly these words. The verdict is MISSES if any finding is "
    "untreated, TREATS only when every finding is.\n"
    # Owner, 2026-10-12: «trebuie să înțeleagă de ce apar defectele și la viitoarele prompturi
    # să se asigure că nu mai sunt».
    "Then say why the defect appeared (cause): in one sentence, which words of the prompts "
    "before invited it. And write the lesson: one general rule for writing every future prompt "
    "so this kind of defect does not appear again — phrased positively (what to write, not what "
    "to avoid), at most 240 characters, with no film title, no scene number and no person's "
    "name, unless the rule is about the office serial's recurring characters.\n"
    'Return only JSON: {{"verdict": "TREATS" | "MISSES", "findings": [{{"finding": "the '
    'finding in a few words", "treated": true | false, "by": "the new sentence that treats '
    'it, or empty", "why_not": "for an untreated finding, why it is not treated; empty when '
    'treated"}}], "cause": "which words of the prompts before invited the defect", "lesson": '
    '"the general rule for future prompts", "reason_ro": "one sentence in Romanian for the '
    'Owner: what is treated and what is not"}}.\n'
)
#: Added to her review of his second rewrite in the rung (2026-10-12).
_SECOND_REVIEW_NOTE = (
    "This is his second rewrite in this round: your review of his first one is in the data "
    "(your_earlier_review). Check above all that every finding you found untreated there is "
    "treated now, by the words your why_not named; the verdict's rules are the same.\n"
)
#: Added to the Video Editor's second rewrite in the rung, with her review inside a boundary
#: of its own (2026-10-12, f06808c9 scenes 3, 4, 7: «Rescrierea nu tratează constatarea …» and
#: the next round asked the same brief — the refusal's words never reached him).
_SECOND_REWRITE_NOTE = (
    "The Director reviewed your rewrite of this shot against quality control's findings and "
    "refused it, so nothing was bought on it. Her review is inside the boundary below: each "
    "finding your rewrite left untreated and why it is not treated (why_not), which words of "
    "the old prompts invited the defect (cause), the findings you did treat with the sentence "
    "that treats them, and your refused prompts. Write the shot once more, following her brief "
    "and the layer's rule: for every untreated finding change exactly the words her why_not "
    "names, or name in their place what the scene asks for; keep the sentences that already "
    "treat a finding; do not send the refused rewrite again.\n"
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
    "Give the shot one ample, specific camera move with its path and tempo (where it starts, "
    "where it ends over the clip's seconds) and write what the subject does as verbs; choose "
    "camera_move from: {moves}. Name colours in words. Return only JSON with this shot: "
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
#: The same rule for a shot of the office serial, whose prompts the studio composes from the
#: fields `SERIAL_STILL_FIELDS` and `SERIAL_MOTION_FIELDS` read (2026-10-12).
_SERIAL_LAYER_RULE = {
    MOTION: (
        "This shot belongs to the office serial and the studio composes its prompts from your "
        "fields. Only the movement is rewritten: give camera_move, ending_frame and emotion "
        "anew. The picture is composed from action and the people in frame, so action stays "
        "word for word as it was; subject, environment, camera, lighting, composition and "
        "motion are not read for a serial shot."
    ),
    STILL: (
        "This shot belongs to the office serial and the studio composes its prompts from your "
        "fields, reading only these. The picture: the series' look and the room (fixed), the "
        "fixed framing for the shot's size on the first person of in_frame (fixed), the people "
        "of in_frame as their bibles describe them (fixed), then the FIRST moment of action — "
        "each person's clause up to the comma that begins their next moment — then emotion, "
        "background and continuity while there is room. The clip: camera_move with its path, "
        "the whole action as the chain of movement, ending_frame, the people's faces kept. So "
        "rewrite action (the people in frame doing their first moment, named first; anyone "
        "else at the frame's edge or off camera, never facing them across the frame unless "
        "the shot is a two-shot), emotion, background, continuity, ending_frame and "
        "camera_move; subject, environment, camera, lighting, composition and motion are not "
        "read for a serial shot."
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
        reason = str(payload.get("reason") or "")
        brief = {
            "at": str(event.timestamp)[:16],
            "layer": payload.get("layer"),
            "rewritten": payload.get("rewritten"),
            # The rewrite came back with the same words (the flag since 2026-10-12; the words
            # for the attempts recorded before it).
            "same_prompt": bool(payload.get("same_prompt")) or "același prompt" in reason,
            "diagnosis": payload.get("diagnosis"),
            "avoid": payload.get("avoid") or [],
            "change": payload.get("change") or [],
        }
        if not payload.get("rewritten"):
            # An attempt that rewrote nothing (her brief refused, his rewrite blocked, her
            # review of his rewrite MISSES): she is told why, so she does not write the same
            # brief again (2026-10-11; the review since 2026-10-12).
            brief["reason"] = reason
        if payload.get("review_verdict") or payload.get("review_attempts"):
            brief["review_verdict"] = payload.get("review_verdict")
            brief["review_reason_ro"] = str(payload.get("review_reason_ro") or "")
            # Why the defect appeared, why a finding stayed untreated, and the rule she drew
            # from it (2026-10-12, f06808c9 scenes 3, 4, 7: the next brief asked the same
            # thing because none of this reached it).
            brief["cause"] = str(payload.get("cause") or "")
            brief["why_not"] = untreated_findings(payload)
            brief["lesson"] = str(payload.get("lesson") or "")
        briefs.append(brief)
    return briefs


def untreated_findings(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Every finding her reviews of a brief's rewrites left untreated, with why, oldest round
    first and each finding once: from the rounds (``review_attempts``, since 2026-10-12) or
    the last review's findings."""
    rounds = [item for item in payload.get("review_attempts") or [] if isinstance(item, dict)]
    lists = [item.get("findings") or [] for item in rounds] or [payload.get("review_findings")]
    seen: set[str] = set()
    found: list[dict[str, str]] = []
    for findings in lists:
        for item in findings or []:
            if not isinstance(item, dict) or item.get("treated"):
                continue
            finding = " ".join(str(item.get("finding") or "").split())
            if not finding or finding.lower() in seen:
                continue
            seen.add(finding.lower())
            found.append({"finding": finding, "why_not": str(item.get("why_not") or "")})
    return found[:MAX_FAILURES_SHOWN]


def _brief_in_short(brief: dict[str, Any]) -> dict[str, Any]:
    """An older brief beyond the ones shown whole: its diagnosis and how it ended, so no
    diagnosis that failed is written again however long the scene's history is."""
    return {
        key: brief.get(key)
        for key in ("at", "layer", "rewritten", "diagnosis", "review_verdict", "cause")
        if brief.get(key) not in (None, "", [])
    }


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
        if not brief.get("rewritten") and not brief.get("same_prompt"):
            continue
        # A motion rewrite that landed, or one that came back with the same words (the
        # cyclotron's scene 5, 2026-10-12: asked the same every hour), is a motion attempt on
        # this picture; a still rewrite starts the count again.
        motions = motions + 1 if brief.get("layer") == MOTION else 0
    if motions >= MOTION_REWRITES_BEFORE_STILL:
        return (STILL,)
    return (MOTION, STILL)


def _shot_of(package: dict[str, Any]) -> dict[str, Any]:
    return {name: package.get(name) for name in SHOT_FIELDS if package.get(name) not in (None, "")}


def scene_context(engine: Engine, storyboard_id: str, scene_index: int) -> dict[str, Any] | None:
    """Everything one rewrite of one scene reads, or None when the scene is not one the studio
    rewrites (not filmed, a closed film, no package to rewrite).

    A scene of the office serial (``serial`` True, since 2026-10-12) reads the same, with the
    series' look as its bible (`series_bible`: the board's own bible may be empty, the look is
    never) and the look itself (``look``) for the composer that says its rewritten fields."""
    from app.agents.editorial import is_serial_film  # noqa: PLC0415 - agents import media
    from app.media.prompt_agent import _allowed_text, _film_facts  # noqa: PLC0415
    from app.media.series_look import load_series_look, series_bible  # noqa: PLC0415
    from app.media.shooting_sheet import film_is_closed  # noqa: PLC0415 - it imports us

    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None or film_is_closed(session, storyboard_id):
            return None
        script = session.get(ScriptDraft, board.script_draft_id) if board.script_draft_id else None
        serial = bool(is_serial_film(board, script))
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
        planned = (
            str(package.get("action") or "").strip() or package.get("in_frame")
            if serial
            else any(str(package.get(name) or "").strip() for name in ("subject", "action"))
        )
        if not planned:
            return None
        look = load_series_look() if serial else None
        bible = (
            series_bible(look, str(board.aspect_ratio or "9:16"))
            if serial and look is not None
            else dict(board.visual_bible_json or {})
        )
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
        briefs = earlier_briefs(session, storyboard_id, scene_index)
        context = {
            "storyboard_id": storyboard_id,
            "scene_index": scene_index,
            "title": str(board.title or storyboard_id[:8]),
            "serial": serial,
            "look": look,
            "bible": bible,
            "story": facts.get("story") or {},
            "scene": scene_facts,
            "allowed": _allowed_text(facts),
            "package": package,
            "visual_prompt": str(target.visual_prompt or ""),
            "shot_type": target.shot_type,
            "previous_moves": moves,
            "previous_ending": previous_ending,
            "failures": scene_failures(session, storyboard_id, scene_index),
            "briefs": briefs[-MAX_BRIEFS_SHOWN:],
            "older_briefs": [_brief_in_short(brief) for brief in briefs[:-MAX_BRIEFS_SHOWN]],
            "last_code": last_code,
            "layers": open_layers(session, storyboard_id, scene_index, last_code=last_code),
            "local_move": _local_move(session, storyboard_id, scene_index),
        }
    return context


def _serial_shot(context: dict[str, Any]) -> dict[str, Any]:
    """How a serial shot's picture is composed, for the agents: its size and fixed framing,
    who is in frame, the room — what the stored fields alone do not say (2026-10-12)."""
    from app.media.prompt_agent import _short_name  # noqa: PLC0415 - it imports us

    package = context["package"]
    look = context.get("look") or {}
    people = [
        _short_name(person.get("name"))
        for person in package.get("in_frame") or []
        if isinstance(person, dict) and person.get("name")
    ]
    size = str(package.get("shot_size") or "")
    framing = str((look.get("shot_sizes") or {}).get(size) or "").replace(
        "{name}", people[0] if people else "the speaker"
    )
    return {
        "shot_size": size,
        "fixed_framing": framing,
        "in_frame": people,
        "location": package.get("location"),
        "how_the_still_is_composed": (
            "the series' look, the room, the fixed framing above, the people in frame as "
            "their bibles describe them, the FIRST moment of action (each person's clause up "
            "to the comma that begins their next moment), then emotion, background and "
            "continuity while there is room"
        ),
        "how_the_clip_is_composed": (
            "camera_move with its path and tempo, the whole action as the chain of movement, "
            "the ending frame, the people's faces kept, the room alive, the feeling"
        ),
    }


def _data(context: dict[str, Any], **more: Any) -> str:
    """The context as the agents read it, inside the inert boundary's limits."""
    from app.media.prompt_agent import trim_payload  # noqa: PLC0415 - it imports us

    package = context["package"]
    scene_keys = ("scene_index", "story_purpose", "narration", "seconds", "writer_visual")
    if context.get("serial"):
        # The beat's part, room, lines and background people: who speaks and where they stand.
        scene_keys += ("part", "location", "lines", "background")
    data = {
        "film": {"title": context["title"], "story": context["story"]},
        "scene": {key: context["scene"].get(key) for key in scene_keys},
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
    if context.get("older_briefs"):
        data["older_briefs_in_short"] = context["older_briefs"]
    if context.get("serial"):
        data["serial_shot"] = _serial_shot(context)
    fitted, _dropped = trim_payload(data, MAX_PAYLOAD_CHARS)
    return json.dumps(fitted, ensure_ascii=False, default=str)


# ------------------------------------------------------------------ her brief


def director_brief(
    engine: Engine, registry: Any, context: dict[str, Any], correlation_id: str
) -> dict[str, Any]:
    """The Director's brief for one scene (`SceneBrief`), asked through `structured_run`.

    Returns {"brief": dict | None, "run_id", "agent_id", "reason"}: no brief when no Director is
    active or her answer did not validate twice (the scene then waits, as before).

    She reads the studio's prompt lessons (`prompt_agent.prompt_lessons`) and, in the scene's
    earlier briefs, the reviews of their rewrites — cause, why_not, lesson — so a diagnosis or
    a change that was refused or failed is not asked again (2026-10-12, f06808c9 scenes 3, 4,
    7)."""
    from app.agents.structured import structured_run  # noqa: PLC0415 - it imports services
    from app.media.prompt_agent import prompt_lessons  # noqa: PLC0415 - it imports us

    with Session(engine) as session:
        director = agent_for_role(session, "Director")
        director_id = director.id if director is not None else None
        lessons = prompt_lessons(session)
    if director_id is None or registry is None:
        return {"brief": None, "run_id": None, "agent_id": None, "reason": "Niciun Director activ."}
    layers = tuple(context["layers"])
    failures = context["failures"]
    prompt = (
        _BRIEF_INSTRUCTIONS.format(
            scene=context["scene_index"],
            title=context["title"],
            failures=f"{len(failures)} refusal(s)" if failures else "refused",
            layers=str(context.get("layers_note") or _LAYERS_OPEN.get(layers, "")),
        )
        + (_SERIAL_BRIEF_NOTE if context.get("serial") else "")
        + wrap_in_inert_boundary(
            _data(context, open_layers=list(layers), lessons=lessons), "scene-brief"
        )
    )
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


def serial_rewritten_package(
    context: dict[str, Any], shot: BaseModel, layer: str, brief: dict[str, Any]
) -> dict[str, Any]:
    """A serial scene's package rewritten from the editor's shot on ``layer`` and said again by
    the serial composer, as `write_shot_prompts` says it: the still from the first moment of
    the action, the people in frame and the shot's size; the motion from the camera move, the
    whole action, the ending frame and the feeling.

    Only the fields the composer reads are taken (`SERIAL_STILL_FIELDS`, `SERIAL_MOTION_FIELDS`);
    who is in frame, the room, the shot's size, the look's version and the plan's provenance
    stay as stored. The motion layer keeps the picture: its feeling goes to ``motion_emotion``
    (the still is composed from ``emotion`` too) and the still's words stay as stored, so
    `serial_recomposition` finds nothing to say again afterwards. 2026-10-12, f06808c9 scene
    4: the action named both women's first moments and the still showed them face to face
    where the plan asked a single on Nadia; the rewrite names only Nadia's moment and puts
    Sarah at the frame's edge."""
    from app.media.prompt_agent import (  # noqa: PLC0415 - it imports us
        _serial_camera_move,
        compose_serial_motion,
        compose_serial_prompt,
        strip_on_screen_text,
        strip_style_overrides,
    )

    del brief  # the look's exclusions are the serial's; hers are the record's (`_record_brief`)
    stored = context["package"]
    look = context.get("look") or {}
    new = shot.model_dump()
    merged = dict(stored)

    def clean(text: Any) -> str:
        said = strip_on_screen_text(" ".join(str(text or "").split()))
        # While the series has a look, a rewrite may describe the shot but never restyle it.
        return strip_style_overrides(said) if look.get("in_use") else said

    for name in SERIAL_STILL_FIELDS if layer == STILL else SERIAL_MOTION_FIELDS:
        value = new.get(name)
        if name == "camera_move":
            move = str(value or "").strip().lower()
            if move in lint.CAMERA_MOVES:
                merged["camera_move"] = move
            continue
        said = clean(value)
        if said:
            merged[name] = said
    if layer == MOTION and clean(new.get("emotion")):
        merged["motion_emotion"] = clean(new.get("emotion"))
    still = compose_serial_prompt(merged, look)
    move = _serial_camera_move(merged, list(context["previous_moves"]))
    merged["camera_move"] = move
    merged["motion_prompt"] = compose_serial_motion(merged, look)
    merged["still_prompt"] = (
        str(stored.get("still_prompt") or context["visual_prompt"]) if layer == MOTION else still
    )
    return merged


def _motion_changed(old: dict[str, Any], new: dict[str, Any]) -> bool:
    return any(old.get(name) != new.get(name) for name in MOTION_IDENTITY)


# ------------------------------------------------------------------ her review of his rewrite


def _sentences(text: Any) -> list[str]:
    return [part.strip() for part in _SENTENCE_END.split(" ".join(str(text or "").split())) if part]


def sentence_diff(old: Any, new: Any) -> dict[str, list[str]]:
    """The sentences of ``new`` that ``old`` did not have and the sentences of ``old`` that are
    gone: what a rewrite changed, read sentence by sentence. 2026-10-12, film 1c038a99 scene
    5: the diff of three paid rewrites in a row was empty or touched nothing the refusal
    named, and nobody read it before the redo was bought."""
    before, after = _sentences(old), _sentences(new)
    return {
        "removed": [sentence for sentence in before if sentence not in after],
        "added": [sentence for sentence in after if sentence not in before],
    }


def review_findings(context: dict[str, Any]) -> list[dict[str, Any]]:
    """The findings this rewrite must treat: the finished film's (from `rewrite_for_redo`) and,
    when the scene's newest take is quality control's refusal, that refusal. Older refusals are
    history for the brief, not findings for this rewrite: a panels refusal answered weeks ago
    would make every later rewrite MISS."""
    failures = list(context.get("failures") or [])
    current = [item for item in failures if item.get("kind") == "film"]
    if context.get("last_code") in QUALITY_CODES:
        newest = next((item for item in failures if item.get("kind") != "film"), None)
        if newest is not None:
            current.append(newest)
    return current or failures[:1]


def review_rewrite(
    engine: Engine,
    registry: Any,
    context: dict[str, Any],
    brief: dict[str, Any],
    layer: str,
    package: dict[str, Any],
    visual: str,
    correlation_id: str,
    *,
    earlier: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The Director's review of the rewritten prompts against the findings (`RewriteReview`),
    asked through `structured_run` before anything is stored or bought.

    Returns {"verdict": TREATS | MISSES | None, "reason_ro", "findings", "cause", "lesson",
    "run_id", "reason"}: no verdict when no Director is active or her answer did not validate
    twice, and the caller fails closed — nothing is bought on words nobody verified (Owner,
    2026-10-12: «tratează problema? Promptul trebuie revizuit»). ``earlier`` is her review of
    his first rewrite in the rung, when this is his second: she checks the findings it left
    untreated first."""
    from app.agents.structured import structured_run  # noqa: PLC0415 - it imports services
    from app.media.prompt_agent import trim_payload  # noqa: PLC0415 - it imports us

    with Session(engine) as session:
        director = agent_for_role(session, "Director")
        director_id = director.id if director is not None else None
    if director_id is None or registry is None:
        return _no_review(None, "niciun Director activ care să verifice rescrierea")
    stored = context["package"]
    old_still = str(stored.get("still_prompt") or context["visual_prompt"])
    old_motion = str(stored.get("motion_prompt") or "")
    new_motion = str(package.get("motion_prompt") or "")
    data = {
        "findings": review_findings(context),
        "director_brief": {
            key: brief.get(key) for key in ("layer", "diagnosis", "avoid", "change")
        },
        "prompts_before": {"still": old_still, "motion": old_motion},
        "prompts_after": {"still": visual, "motion": new_motion},
        "difference": {
            "still": sentence_diff(old_still, visual),
            "motion": sentence_diff(old_motion, new_motion),
        },
    }
    if context.get("serial"):
        data["serial_shot"] = _serial_shot(context)
    if earlier:
        data["your_earlier_review"] = {
            "verdict": earlier.get("verdict"),
            "findings": earlier.get("findings") or [],
            "cause": earlier.get("cause") or "",
        }
    fitted, _dropped = trim_payload(data, MAX_PAYLOAD_CHARS)
    prompt = (
        _REVIEW_INSTRUCTIONS.format(
            scene=context["scene_index"], title=context["title"], layer=layer
        )
        + (_SECOND_REVIEW_NOTE if earlier else "")
        + wrap_in_inert_boundary(
            json.dumps(fitted, ensure_ascii=False, default=str), "rewrite-review"
        )
    )
    parsed, first, second = structured_run(
        engine,
        registry,
        director_id,
        REVIEW_TASK,
        prompt,
        REVIEW_TEMPLATE,
        correlation_id,
        RewriteReview,
        "",
        summary=(
            f"Verific dacă rescrierea scenei {context['scene_index']} din "
            f"«{context['title'][:60]}» tratează constatările înainte să cumpărăm ceva pe ea."
        ),
        max_tokens=1600,
    )
    last = second or first
    if parsed is None:
        return _no_review(
            last.get("id"),
            "verificarea rescrierii nu a respectat forma cerută nici a doua oară "
            f"({last.get('error_detail') or last.get('status')})",
        )
    return {
        "verdict": parsed.verdict,
        "reason_ro": parsed.reason_ro,
        "findings": [item.model_dump() for item in parsed.findings],
        "cause": parsed.cause,
        "lesson": parsed.lesson,
        "run_id": last.get("id"),
        "reason": "",
    }


def _no_review(run_id: str | None, reason: str) -> dict[str, Any]:
    """A review that could not be made: no verdict, and the reason; the caller fails closed."""
    return {
        "verdict": None,
        "reason_ro": "",
        "findings": [],
        "cause": "",
        "lesson": "",
        "run_id": run_id,
        "reason": reason,
    }


# ------------------------------------------------------------------ what a review teaches

#: A scene named by its number: a note on one scene, not a rule for every prompt.
_SCENE_NUMBER = re.compile(
    r"\b(?:scene|scenes|scena|scenele|scenei)\s*(?:no\.?\s*)?#?\d+\b", re.IGNORECASE
)
#: Words that say nothing of a lesson's content, left out when two lessons are compared.
_LESSON_STOPWORDS = frozenset(
    "the and for with that this from into its are was were has have had but not any all each "
    "them they their there than then when where which who what while will would should must "
    "can may also more most other such very just every".split()
)


def _lesson_words(text: str) -> set[str]:
    """A lesson's content words, lower-cased, plurals folded: what `lesson_overlap` compares."""
    words: set[str] = set()
    for word in re.findall(r"[^\W\d_]+|\d+", str(text or "").lower()):
        if len(word) < 3 or word in _LESSON_STOPWORDS:
            continue
        if word.endswith("ies") and len(word) > 4:
            word = word[:-3] + "y"
        elif word.endswith("s") and not word.endswith("ss") and len(word) > 3:
            word = word[:-1]
        words.add(word)
    return words


def lesson_overlap(new: str, known: str) -> float:
    """The share of ``new``'s content words that ``known`` already says, 0..1: at
    `LESSON_OVERLAP` or more the studio already has the lesson, and it is not written again."""
    said = _lesson_words(new)
    if not said:
        return 1.0
    return len(said & _lesson_words(known)) / len(said)


def lesson_not_general(lesson: str, context: dict[str, Any]) -> str:
    """Why ``lesson`` is a note on this film rather than a rule for every prompt (its title, a
    scene's number), or "" when it is a rule. Names are the review's to leave out (her
    instructions): a serial's recurring characters may be named, and nothing here can tell a
    person's name from a word."""
    said = " ".join(str(lesson or "").split())
    if not said:
        return "recenzia nu a scris nicio lecție"
    title = " ".join(str(context.get("title") or "").split()).lower()
    if len(title) >= 4 and title in said.lower():
        return "lecția numește filmul; nu e o regulă pentru orice prompt"
    if _SCENE_NUMBER.search(said):
        return "lecția numește o scenă; nu e o regulă pentru orice prompt"
    return ""


def learn_from_review(
    session: Session, review: dict[str, Any], context: dict[str, Any]
) -> tuple[bool, str]:
    """The lesson of a review that passed a rewrite, kept for every future prompt
    (`prompt_agent.record_prompt_lesson`, read by the shot writer, the rewrites and every
    brief), unless it is a note on this film or the studio already says it. Returns (recorded,
    why not). Inside the caller's write transaction. Owner, 2026-10-12: «DIRECTOAREA ACCEPTĂ
    DEFECTELE MICI! DAR TREBUIE SĂ ÎNȚELEAGĂ DE CE APAR DEFECTELE ȘI LA VIITOARELE PROMPTURI SĂ
    SE ASIGURE CĂ NU MAI SUNT!»"""
    from app.media.prompt_agent import (  # noqa: PLC0415 - it imports us
        prompt_lessons,
        record_prompt_lesson,
    )

    lesson = " ".join(str(review.get("lesson") or "").split())[:LESSON_MAX_CHARS]
    why = lesson_not_general(lesson, context)
    if why:
        return False, why
    for known in prompt_lessons(session, limit=LESSONS_COMPARED):
        if lesson_overlap(lesson, known) >= LESSON_OVERLAP:
            return False, f"studioul are deja lecția: «{known[:160]}»"
    record_prompt_lesson(session, lesson, source_id=review.get("run_id"))
    return True, ""


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


def _editor_rewrite(
    engine: Engine,
    registry: Any,
    editor_id: str,
    context: dict[str, Any],
    brief: dict[str, Any],
    prompt: str,
    correlation_id: str,
) -> dict[str, Any]:
    """His rewrite of the shot from ``prompt``, compiled (or said again by the serial
    composer) and linted, the linter's refusal quoted to him once. Returns {"package",
    "visual", "run_id", "reason"}: no package when his answer did not validate twice or the
    linter blocked it twice."""
    from app.agents.structured import structured_run  # noqa: PLC0415 - it imports services

    index = int(context["scene_index"])
    layer = str(brief["layer"])
    serial = bool(context.get("serial"))
    visual = context["visual_prompt"]
    refused: list[str] = []
    run_id = None
    for _attempt in (0, 1):
        asked = prompt
        if refused:
            asked += (
                "Your previous rewrite of this shot was refused by the studio's prompt check: "
                + "; ".join(refused)[:800]
                + ". Write it again without that.\n"
            )
        parsed, first, second = structured_run(
            engine,
            registry,
            editor_id,
            REWRITE_TASK,
            asked,
            REWRITE_TEMPLATE,
            correlation_id,
            shot_schema(index, layer, serial=serial),
            "",
            summary=(
                f"Rescriu scena {index} din «{context['title'][:60]}» după brief-ul Directoarei."
            ),
            max_tokens=3000,
            temperature=0.3,
        )
        last = second or first
        run_id = last.get("id")
        if parsed is None:
            return {
                "package": None,
                "visual": visual,
                "run_id": run_id,
                "reason": (
                    "Rescrierea lui Kael nu a respectat forma cerută nici a doua oară "
                    f"({last.get('error_detail') or last.get('status')})."
                ),
            }
        rewrite = serial_rewritten_package if serial else rewritten_package
        candidate = rewrite(context, parsed, layer, brief)
        candidate_visual = (
            visual if layer == MOTION else str(candidate.get("still_prompt") or visual)
        )
        refused = _lint_blocks(context, candidate, candidate_visual)
        if not refused:
            return {
                "package": candidate,
                "visual": candidate_visual,
                "run_id": run_id,
                "reason": "",
            }
    return {
        "package": None,
        "visual": visual,
        "run_id": run_id,
        "reason": "Verificarea promptului a blocat rescrierea: " + "; ".join(refused)[:600],
    }


def _reviewed(
    engine: Engine,
    registry: Any,
    context: dict[str, Any],
    brief: dict[str, Any],
    layer: str,
    package: dict[str, Any],
    visual: str,
    correlation_id: str,
    earlier: dict[str, Any] | None,
) -> dict[str, Any]:
    """Her review of one rewrite (`review_rewrite`); a fault is a review that could not be
    made, and the caller fails closed."""
    try:
        return review_rewrite(
            engine,
            registry,
            context,
            brief,
            layer,
            package,
            visual,
            correlation_id,
            earlier=earlier,
        )
    except Exception as exc:  # noqa: BLE001 - a fault waits; it never buys
        logger.warning("rewrite_review_failed", extra={"error": type(exc).__name__})
        return _no_review(
            None, f"verificarea rescrierii nu a putut fi făcută ({type(exc).__name__})"
        )


def _kept_findings(findings: Any) -> list[dict[str, Any]]:
    """Her review's findings as the record keeps them: each with its text (``finding``),
    whether it is treated, the new sentence that treats it (``by``) and, untreated, why
    (``why_not``)."""
    return [
        {
            "finding": str(item.get("finding") or ""),
            "treated": bool(item.get("treated")),
            "by": str(item.get("by") or ""),
            "why_not": str(item.get("why_not") or ""),
        }
        for item in findings or []
        if isinstance(item, dict)
    ]


def _round_record(
    number: int, written: dict[str, Any], layer: str, review: dict[str, Any]
) -> dict[str, Any]:
    """One round of the rung as the brief's record keeps it: his words, her verdict and why."""
    package = written["package"] or {}
    return {
        "round": number,
        "layer": layer,
        "rewrite_run_id": written.get("run_id"),
        "review_run_id": review.get("run_id"),
        "verdict": review.get("verdict"),
        "reason_ro": str(review.get("reason_ro") or ""),
        "reason": str(review.get("reason") or ""),
        "cause": str(review.get("cause") or ""),
        "lesson": str(review.get("lesson") or ""),
        "findings": _kept_findings(review.get("findings")),
        "still_prompt": str(written.get("visual") or ""),
        "motion_prompt": str(package.get("motion_prompt") or ""),
    }


def _same_words(record: dict[str, Any], visual: str, package: dict[str, Any]) -> bool:
    """Whether his second rewrite says what the refused one said, word for word."""

    def said(text: Any) -> str:
        return " ".join(str(text or "").split())

    return said(record.get("still_prompt")) == said(visual) and said(
        record.get("motion_prompt")
    ) == said(package.get("motion_prompt"))


def _second_rewrite_note(record: dict[str, Any]) -> str:
    """Her review of his refused rewrite, for his second: each untreated finding with why, the
    cause, the findings he did treat with their sentence, and his refused prompts — inside a
    boundary of its own, since the findings quote quality control's words."""
    untreated = [
        {"finding": item["finding"], "why_not": item["why_not"]}
        for item in record["findings"]
        if not item["treated"]
    ]
    treated = [
        {"finding": item["finding"], "by": item["by"]}
        for item in record["findings"]
        if item["treated"]
    ]
    data = {
        "verdict": record["verdict"],
        "reason_ro": record["reason_ro"],
        "untreated": untreated,
        "treated": treated,
        "cause": record["cause"],
        "refused_prompts": {"still": record["still_prompt"], "motion": record["motion_prompt"]},
    }
    return _SECOND_REWRITE_NOTE + wrap_in_inert_boundary(
        json.dumps(data, ensure_ascii=False, default=str), "rewrite-feedback"
    )


def _second_rewrite_failed(outcome: dict[str, Any], why: str) -> dict[str, Any]:
    """His second rewrite came to nothing her review could read (his answer, the linter, the
    old words or the refused ones again): her refusal of the first stands, and nothing is
    stored or bought."""
    outcome["not_treating"] = True
    outcome["reason"] = (
        "Rescrierea nu tratează constatarea: "
        + str(outcome.get("review_reason_ro") or "")
        + f" A doua rescriere, cu observațiile ei: {why}"
    )
    return outcome


def rewrite_scene(
    engine: Engine,
    registry: Any,
    context: dict[str, Any],
    brief: dict[str, Any],
    correlation_id: str,
) -> dict[str, Any]:
    """The Video Editor's rewrite of one scene from the Director's brief, compiled (or, for a
    serial scene, said again by the serial composer), linted, reviewed by her against the
    findings and stored on that scene only. Returns {"rewritten": bool, "layer", "reason",
    "run_id", "review_run_id", "review_verdict", "review_reason_ro", "review_findings",
    "review_cause", "review_lesson", "review_attempts", "old_still_prompt", "still_prompt",
    "old_motion_prompt", "motion_prompt"}; ``same_prompt`` True when his words came back the
    same, ``not_treating`` True when her review said MISSES, ``review_unavailable`` True when
    nobody could review it — nothing is stored in the last two cases either.

    A rewrite her review refused is rewritten once more in the same rung, with her words: each
    untreated finding and why it is not treated (2026-10-12, f06808c9 scenes 3, 4, 7: the
    refused rewrites ended the rung and the next one asked the same brief). Only a second miss
    stores nothing. A rewrite she passes stores the scene and her lesson (`learn_from_review`)."""
    from app.media.prompt_agent import PROMPT_ROLE, prompt_lessons  # noqa: PLC0415

    index = int(context["scene_index"])
    layer = str(brief["layer"])
    serial = bool(context.get("serial"))
    outcome: dict[str, Any] = {"rewritten": False, "layer": layer, "reason": "", "run_id": None}
    with Session(engine) as session:
        editor = agent_for_role(session, PROMPT_ROLE)
        editor_id = editor.id if editor is not None else None
        lessons = prompt_lessons(session)
    if editor_id is None or registry is None:
        outcome["reason"] = "Niciun Video Editor activ."
        return outcome
    base = _REWRITE_INSTRUCTIONS.format(
        scene=index,
        title=context["title"],
        layer=(_SERIAL_LAYER_RULE if serial else _LAYER_RULE)[layer],
        # The whole vocabulary («Mișcare v2», 2026-10-12): the old ten slow moves alone sent
        # every redo back to a slow move.
        moves=", ".join(lint.CAMERA_MOVES),
    ) + wrap_in_inert_boundary(
        _data(context, director_brief=brief, lessons=lessons), "scene-rewrite"
    )
    stored = context["package"]
    rounds: list[dict[str, Any]] = []
    review: dict[str, Any] = {}
    package: dict[str, Any] = {}
    visual = context["visual_prompt"]
    layer_done = layer
    for number in range(1, REWRITES_PER_RUNG + 1):
        note = _second_rewrite_note(rounds[-1]) if rounds else ""
        written = _editor_rewrite(
            engine, registry, editor_id, context, brief, base + note, correlation_id
        )
        outcome["run_id"] = written["run_id"]
        if written["package"] is None:
            if rounds:
                return _second_rewrite_failed(outcome, str(written["reason"]))
            outcome["reason"] = str(written["reason"])
            return outcome
        package, visual = written["package"], str(written["visual"])
        still_changed = " ".join(visual.split()) != " ".join(context["visual_prompt"].split())
        if not still_changed and not _motion_changed(stored, package):
            if rounds:
                return _second_rewrite_failed(
                    outcome, "a dat din nou cuvintele de dinainte ale scenei."
                )
            outcome["reason"] = "Rescrierea a dat același prompt; nimic nou de cumpărat."
            # The caller may try the other layer: a motion rewrite that changed nothing on a
            # picture that stays is the picture's turn (MOTION_REWRITES_BEFORE_STILL).
            outcome["same_prompt"] = True
            return outcome
        if rounds and _same_words(rounds[-1], visual, package):
            # The words she refused, asked again: they cannot treat what they did not.
            return _second_rewrite_failed(
                outcome, "a dat aceleași cuvinte pe care Directoarea le-a refuzat."
            )
        layer_done = STILL if still_changed else MOTION
        # Her review, before anything is stored: does the rewrite treat the finding? (Owner,
        # 2026-10-12: «Nu ai cum să faci de 5 ori aceeași greșeală!») A review that could not
        # be made fails closed: nothing is bought on words nobody verified.
        review = _reviewed(
            engine,
            registry,
            context,
            brief,
            layer_done,
            package,
            visual,
            correlation_id,
            rounds[-1] if rounds else None,
        )
        rounds.append(_round_record(number, written, layer_done, review))
        outcome.update(
            review_run_id=review.get("run_id"),
            review_verdict=review.get("verdict"),
            review_reason_ro=str(review.get("reason_ro") or ""),
            review_findings=_kept_findings(review.get("findings")),
            review_cause=str(review.get("cause") or ""),
            review_lesson=str(review.get("lesson") or ""),
            review_attempts=rounds,
        )
        if review.get("verdict") != MISSES:
            break
    if review.get("verdict") == MISSES:
        outcome["not_treating"] = True
        outcome["reason"] = "Rescrierea nu tratează constatarea: " + str(review.get("reason_ro"))
        if len(rounds) > 1:
            outcome["reason"] += " (și a doua rescriere, cu observațiile ei, a fost refuzată)"
        return outcome
    if review.get("verdict") != TREATS:
        outcome["review_unavailable"] = True
        outcome["reason"] = (
            f"Rescrierea nu a putut fi verificată față de constatări ({review.get('reason')}); "
            "nu se cumpără nimic pe cuvinte pe care nimeni nu le-a verificat."
        )
        return outcome
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
        learned, unlearned = learn_from_review(session, review, context)
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
                # Her review of the words stored. CONTRACT (2026-10-12): ``findings`` keeps, for
                # every finding quality control gave, its text (``finding``) and the new
                # sentence that treats it (``by``), with ``treated`` and ``why_not``: what the
                # purchase that follows is checked against — after the new still (and its
                # clip) is bought, each finding must be gone from the picture. ``cause`` and
                # ``lesson`` say why the defect appeared and the rule drawn from it;
                # ``rounds`` counts his rewrites in the rung, ``refused`` the ones she refused
                # before this one (each with its findings and why_not).
                "review": {
                    "verdict": review.get("verdict"),
                    "reason_ro": review.get("reason_ro"),
                    "findings": _kept_findings(review.get("findings")),
                    "run_id": review.get("run_id"),
                    "cause": str(review.get("cause") or ""),
                    "lesson": str(review.get("lesson") or ""),
                    "lesson_recorded": learned,
                    "rounds": len(rounds),
                    "refused": [
                        {
                            key: item[key]
                            for key in ("round", "review_run_id", "reason_ro", "cause", "findings")
                        }
                        for item in rounds[:-1]
                    ],
                },
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
        lesson_recorded=learned,
        lesson_skipped=unlearned,
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
            rounds = list(done.get("review_attempts") or [])
            if done.get("rewritten"):
                again = ""
                if len(rounds) > 1:
                    # His second rewrite in the rung, from her review of the first (2026-10-12).
                    again = (
                        " a doua oară, după observațiile Directoarei la prima rescriere ("
                        + str(rounds[0].get("reason_ro") or "")[:200]
                        + ")"
                    )
                answer = (
                    f"Am rescris scena {index} ({redone}){again}. "
                    f"Promptul nou de mișcare: {str(done.get('motion_prompt') or '')[:300]}"
                )
            elif done.get("not_treating"):
                # Her review refused his words (2026-10-12): the letter says so, and why, so
                # the register shows a rewrite that was not bought rather than one that failed.
                times = " de două ori" if len(rounds) > 1 else ""
                answer = (
                    f"Am rescris scena {index}{times}, dar la verificare Directoarea a refuzat "
                    f"rescrierea și nu se cumpără nimic pe ea. {done.get('reason')}"
                )
            elif done.get("review_unavailable"):
                answer = (
                    f"Am rescris scena {index}, dar rescrierea nu a putut fi verificată față de "
                    f"constatări și nu se cumpără nimic pe ea. {done.get('reason')}"
                )
            else:
                answer = f"Nu am putut rescrie scena {index}: {done.get('reason')}"
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
                # A rewrite that came back with the same words: counted as a motion attempt
                # by `open_layers`, so the picture's turn comes (2026-10-12, the cyclotron).
                "same_prompt": bool(done.get("same_prompt")),
                "reason": done.get("reason") or "",
                # Her review of his rewrite (2026-10-12): MISSES is why nothing was stored, and
                # the next brief is shown it (`earlier_briefs`).
                "review_verdict": done.get("review_verdict"),
                "review_reason_ro": done.get("review_reason_ro") or "",
                "review_run_id": done.get("review_run_id"),
                "not_treating": bool(done.get("not_treating")),
                # Why the defect appeared and the rule she drew from it, every finding of her
                # last review with why_not, and each round of his rewrites with her verdict
                # (2026-10-12): the next brief reads them (`earlier_briefs`), so a refused
                # diagnosis or change is not asked again.
                "cause": done.get("review_cause") or "",
                "lesson": done.get("review_lesson") or "",
                "lesson_recorded": bool(done.get("lesson_recorded")),
                "lesson_skipped": done.get("lesson_skipped") or "",
                "review_findings": done.get("review_findings") or [],
                "review_attempts": done.get("review_attempts") or [],
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


#: The reason a serial scene's words are said again on the record (`SCENE_PROMPTS_REWRITTEN`).
SERIAL_RECOMPOSE_REASON = "serial_recompose"
#: The reason a serial scene whose words are already today's is made again on them (the same
#: record, the same words): a technical refusal of the still gate is answered with another
#: picture on the same words.
SERIAL_REROLL_REASON = "serial_reroll"
#: What quality control's refusal of a serial take says about its words. CONTENT: the picture
#: or the clip is not what the scene asks for, so the words must change (her brief, his
#: rewrite, her review). TECHNICAL: a measured defect of one picture — panels, blur, a
#: degenerate picture, a check that could not run — which another picture on the same words
#: may answer.
CONTENT_REFUSAL = "content"
TECHNICAL_REFUSAL = "technical"
#: The still gate's content refusals, by its own fixed phrases (`still_gate.decide`): the gate
#: writes only its Romanian reasons on the take (`stills_stage._set_verdicts`), never its
#: violation codes, so they are read back from the phrases. Anything else the gate says is
#: technical.
CONTENT_REFUSAL_PHRASES: tuple[str, ...] = (
    "nu arată ce cere scena",
    "nu arată ce cere planul",
    "text lizibil",
    "interzice fețele",
    "încalcă biblia",
    "aspectul filmului",
)


def refusal_kind(code: str | None, detail: str | None) -> str:
    """CONTENT_REFUSAL or TECHNICAL_REFUSAL for one refused take of quality control's. A clip
    QC block is always about what the clip shows or does; a gate refusal is read by its
    phrases; a refusal that says nothing is treated as content, so the same words are never
    bought blind (f06808c9 scene 4, 2026-10-12: the same two women asked again with another
    seed, for a refusal that named them)."""
    if code == "QC.CLIP":
        return CONTENT_REFUSAL
    said = " ".join(str(detail or "").split()).lower()
    if not said:
        return CONTENT_REFUSAL
    if any(phrase in said for phrase in CONTENT_REFUSAL_PHRASES):
        return CONTENT_REFUSAL
    return TECHNICAL_REFUSAL


def serial_refusal(
    session: Session, storyboard_id: str, scene_index: int
) -> tuple[str | None, str | None, str]:
    """The scene's newest refusal as `last_failure_code` reads it, with its kind
    (`refusal_kind`) and the words quality control wrote on the take: (code, kind, detail);
    (None, None, "") when the scene's newest take came out right or nothing refused it."""
    from app.media.assembler import take_failure  # noqa: PLC0415 - a large module

    for row in scene_takes(session, storyboard_id, scene_index):
        if row.status in ("PAID", "APPROVED", "SUBMITTED"):
            return None, None, ""
        record = take_failure(row)
        if record is not None:
            code = str(record.code or record.kind or "")
            detail = str(row.failure_detail or "")
            return code, refusal_kind(code, detail), detail
    return None, None, ""


def _serial_scene(engine: Engine, storyboard_id: str) -> bool:
    """Whether the film is an episode of the office serial (its scenes are composed; their
    words are said again by the composer, and rewritten by the Video Editor from a brief only
    for a content refusal)."""
    from app.agents.editorial import is_serial_film  # noqa: PLC0415 - agents import media

    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            return False
        script = session.get(ScriptDraft, board.script_draft_id) if board.script_draft_id else None
        return bool(is_serial_film(board, script))


def serial_recomposition(
    session: Session, storyboard_id: str, scene_index: int
) -> dict[str, Any] | None:
    """A serial scene's prompts composed again from its stored plan, as the studio composes
    them today, when they differ from the stored ones; None when they do not, when the film
    is not the serial's, or when the scene has no plan. Reads only; 0 credits, no model.

    2026-10-12 (f06808c9, scenes 3 and 4): the stored stills carried the plan's camera path
    and chain of moments that an image model draws as stacked panels; the composer was fixed
    (48bbcd1) and nothing said the stored words again — the sheet repair runs only on lint
    blockers, and the Director's rewrite (`scene_context`) does not read serial scenes, so
    the film waited for the Owner. A serial scene's words are the composer's, not a model's
    rewrite: said again with today's composer, the scene is hers to redo."""
    from app.agents.editorial import is_serial_film  # noqa: PLC0415 - agents import media
    from app.media.prompt_agent import (  # noqa: PLC0415 - it imports this module's neighbours
        _serial_camera_move,
        compose_serial_motion,
        compose_serial_prompt,
    )
    from app.media.series_look import load_series_look  # noqa: PLC0415

    board = session.get(Storyboard, storyboard_id)
    if board is None:
        return None
    script = session.get(ScriptDraft, board.script_draft_id) if board.script_draft_id else None
    if not is_serial_film(board, script):
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
    stored = dict(target.prompt_json or {})
    if not str(stored.get("action") or "").strip() and not stored.get("in_frame"):
        return None
    moves = [
        str((row.prompt_json or {}).get("camera_move") or "")
        for row in rows
        if int(row.scene_index) < scene_index
        and str(row.scene_kind or "LIVE").upper() == "LIVE"
        and (row.prompt_json or {}).get("camera_move")
    ]
    look = load_series_look()
    old_still = " ".join(str(stored.get("still_prompt") or target.visual_prompt or "").split())
    old_motion = " ".join(str(stored.get("motion_prompt") or "").split())
    new_still = " ".join(compose_serial_prompt(stored, look).split())
    move = _serial_camera_move(stored, moves)
    new_motion = " ".join(compose_serial_motion({**stored, "camera_move": move}, look).split())
    if not new_still or (new_still == old_still and new_motion == old_motion):
        return None
    compiled = {"still_prompt": new_still, "motion_prompt": new_motion, "camera_move": move}
    return {
        "scene_index": scene_index,
        "old_still_prompt": old_still,
        "still_prompt": new_still,
        "old_motion_prompt": old_motion,
        "motion_prompt": new_motion,
        "package": {**stored, **compiled},
        "visual_prompt": new_still,
        "stored_package": stored,
        "stored_visual": target.visual_prompt,
    }


def _say_serial_words_again(
    session: Session,
    target: StoryboardScene,
    rewrite: dict[str, Any],
    correlation_id: str,
) -> None:
    """A serial scene's words as today's composer says them, stored and written as the
    Director's decision on the scene (`SCENE_PROMPTS_REWRITTEN_EVENT`, layer ``still``: the
    scene's hold lifts and the stills step buys again on the new words). Inside the caller's
    write transaction."""
    from app.media.assembler import (  # noqa: PLC0415 - a large module
        DIRECTOR_REWRITE,
        SCENE_PROMPTS_REWRITTEN_EVENT,
    )

    target.prompt_json = dict(rewrite["package"])
    target.visual_prompt = str(rewrite["visual_prompt"])
    append_event(
        session,
        SCENE_PROMPTS_REWRITTEN_EVENT,
        "storyboard",
        str(target.storyboard_id),
        1,
        {
            "scene_index": int(target.scene_index),
            "old_still_prompt": rewrite["old_still_prompt"],
            "still_prompt": rewrite["still_prompt"],
            "old_motion_prompt": rewrite["old_motion_prompt"],
            "motion_prompt": rewrite["motion_prompt"],
            "reason": SERIAL_RECOMPOSE_REASON,
            "decided_by": DIRECTOR_REWRITE,
            "layer": "still",
            "camera_move": rewrite["package"].get("camera_move"),
        },
        correlation_id,
    )


def recompose_serial_scene(
    engine: Engine, storyboard_id: str, scene_index: int, correlation_id: str
) -> dict[str, Any]:
    """The serial rung of the ladder, before any model: the scene's words said again with
    today's composer when they changed (`_say_serial_words_again`, 0 credits). Returns the
    rung's outcome; a scene whose words are already today's is not rewritten here, and says
    what comes next:

    - nothing refused it: ``rewritten`` False, the pictures are made again, not the words;
    - the still gate refused it for a technical fault (`TECHNICAL_REFUSAL`): another picture on
      the same words — her decision on the record (`SERIAL_REROLL_REASON`), the hold lifts, the
      attempts count again, the motion is bought on a seed moved past the clips the scene had
      (`assembler._scene_seed`);
    - quality control refused what it shows (`CONTENT_REFUSAL`: the gate's content phrases, a
      clip QC block): ``rewritten`` False and ``needs_brief`` True — the words must change,
      and `rewrite_failed_scene` goes on to her brief, his rewrite and her review. Until
      2026-10-12 every refusal was a reroll (f06808c9 scene 4: the same two women asked
      again with another seed, for a refusal that named them)."""
    from app.media.assembler import (  # noqa: PLC0415 - a large module
        DIRECTOR_REWRITE,
        SCENE_PROMPTS_REWRITTEN_EVENT,
    )
    from app.media.shooting_sheet import film_is_closed  # noqa: PLC0415 - it imports us

    outcome: dict[str, Any] = {
        "scene_index": scene_index,
        "rewritten": False,
        "layer": None,
        "reason": "",
        "summary_ro": "",
    }
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        if film_is_closed(session, storyboard_id):
            outcome["reason"] = "Filmul este închis; nimic nu se mai rescrie."
            return outcome
        rewrite = serial_recomposition(session, storyboard_id, scene_index)
        target = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id,
                StoryboardScene.scene_index == scene_index,
            )
        )
        if target is None:
            outcome["reason"] = "Scena nu există."
            return outcome
        if rewrite is None:
            code, kind, detail = serial_refusal(session, storyboard_id, scene_index)
            if code not in QUALITY_CODES:
                outcome["reason"] = (
                    f"Scena {scene_index} a serialului are deja cuvintele de azi; se refac doar "
                    "imaginile, nu cuvintele."
                )
                return outcome
            if kind == CONTENT_REFUSAL:
                what = "imaginea" if code == STILL_GATE_CODE else "cadrul"
                outcome.update(
                    needs_brief=True,
                    refused_code=code,
                    refusal_kind=kind,
                    reason=(
                        f"Scena {scene_index} a serialului are cuvintele de azi, dar controlul "
                        f"calității a refuzat ce arată {what} ({code}: "
                        f"{' '.join(detail.split())[:160] or 'fără detalii'}); aceleași cuvinte "
                        "nu se mai cumpără, Directoarea le rescrie."
                    ),
                )
                return outcome
            stored = dict(target.prompt_json or {})
            append_event(
                session,
                SCENE_PROMPTS_REWRITTEN_EVENT,
                "storyboard",
                storyboard_id,
                1,
                {
                    "scene_index": scene_index,
                    "old_still_prompt": target.visual_prompt,
                    "still_prompt": target.visual_prompt,
                    "old_motion_prompt": stored.get("motion_prompt"),
                    "motion_prompt": stored.get("motion_prompt"),
                    "reason": SERIAL_REROLL_REASON,
                    "decided_by": DIRECTOR_REWRITE,
                    "layer": STILL,
                    "refused_code": code,
                    "refusal_kind": kind,
                    "camera_move": stored.get("camera_move"),
                },
                correlation_id,
            )
            outcome.update(
                rewritten=True,
                layer=STILL,
                reason=SERIAL_REROLL_REASON,
                refusal_kind=kind,
                summary_ro=(
                    f"Scena {scene_index} a serialului are deja cuvintele de azi; imaginea ei, "
                    f"refuzată de controlul calității pentru un defect tehnic ({code}), se reface "
                    "pe aceleași cuvinte, cu altă sămânță."
                ),
            )
            return outcome
        _say_serial_words_again(session, target, rewrite, correlation_id)
    outcome.update(
        rewritten=True,
        layer=STILL,
        reason=SERIAL_RECOMPOSE_REASON,
        summary_ro=(
            f"Scena {scene_index} a serialului a fost compusă din nou cu cuvintele de azi "
            "(un singur moment, încadrare fixă); imaginea se reface."
        ),
    )
    return outcome


def _serial_words_said_again(
    engine: Engine, storyboard_id: str, scene_index: int, correlation_id: str
) -> bool:
    """Before her brief on a serial scene: its stale words said again with today's composer
    (`_say_serial_words_again`), so the brief reads today's words and the rewrite starts from
    them. True when the words changed; False when they were already today's."""
    from app.media.shooting_sheet import film_is_closed  # noqa: PLC0415 - it imports us

    with Session(engine) as session, session.begin():
        lock_for_write(session)
        if film_is_closed(session, storyboard_id):
            return False
        rewrite = serial_recomposition(session, storyboard_id, scene_index)
        target = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id,
                StoryboardScene.scene_index == scene_index,
            )
        )
        if rewrite is None or target is None:
            return False
        _say_serial_words_again(session, target, rewrite, correlation_id)
        return True


def rewrite_failed_scene(
    engine: Engine, registry: Any, storyboard_id: str, scene_index: int, correlation_id: str
) -> dict[str, Any]:
    """One rung of the ladder for one scene: her brief, his rewrite, her review, their letters
    and the record. Returns {"scene_index", "rewritten", "layer", "reason", "summary_ro"};
    never raises for the agents' faults (the scene then waits, as it did).

    A serial scene's words are the composer's (`compose_serial_prompt`): said again with
    today's composer when they changed, made again on the same words after a technical
    refusal of the gate (`recompose_serial_scene`), and — since 2026-10-12 — rewritten from
    her brief like a factual scene's when quality control refused what they show."""
    outcome: dict[str, Any] = {
        "scene_index": scene_index,
        "rewritten": False,
        "layer": None,
        "reason": "",
        "summary_ro": "",
    }
    if _serial_scene(engine, storyboard_id):
        said = recompose_serial_scene(engine, storyboard_id, scene_index, correlation_id)
        if not said.get("needs_brief"):
            return said
    context = scene_context(engine, storyboard_id, scene_index)
    if context is None:
        outcome["reason"] = (
            "Scena nu este una pe care studioul o rescrie (card, film închis, fără plan)."
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
    studio rewrites (a card, a closed film, a package with no plan, a still he approved):
    its redo goes on as it would have. A serial scene is rewritable (2026-10-12): its stale
    words are said again by today's composer first, 0 credits, so her brief reads today's
    words; the film's findings are content, so the words must change."""
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
    if context.get("serial") and _serial_words_said_again(
        engine, storyboard_id, scene_index, correlation_id
    ):
        context = scene_context(engine, storyboard_id, scene_index)
        if context is None:
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
        # The rewrite came back with the same words: the caller's cue to turn to the picture
        # (2026-10-12: the cyclotron's scenes 4 and 5 were asked the same movement every hour
        # because this flag stopped here, and the Director wrote to the Owner about a tool).
        same_prompt=bool(done.get("same_prompt")),
        # Her review refused his words, or nobody could review them: nothing was stored, and
        # the caller buys nothing on the old words either (2026-10-12).
        not_treating=bool(done.get("not_treating")),
        review_unavailable=bool(done.get("review_unavailable")),
        review_verdict=done.get("review_verdict"),
        review_reason_ro=str(done.get("review_reason_ro") or ""),
        # His rewrites in the rung (a second one after her review refused the first) and
        # whether her lesson became the studio's (2026-10-12).
        review_rounds=len(done.get("review_attempts") or []),
        lesson_recorded=bool(done.get("lesson_recorded")),
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
