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
   (`cause`) and, when there is one, a general rule for every future prompt (`lesson`): a
   rewrite she passes records the lesson for the film's kind, unverified until the picture
   bought on it shows the finding gone (`learn_from_review`), and every later brief reads the
   studio's lessons and, for the scene, the earlier briefs with their reviews' causes, why_not
   and lessons — «la viitoarele prompturi să se asigure că nu mai sunt».
7. Her review is tied to quality control's own findings and to what the layer can change
   (2026-10-12, f06808c9 scenes 3, 4, 7, 16:46-16:48). That day her review of a serial motion
   rewrite added two diagnoses of her own as findings and refused the rewrite although the
   finding quality control gave (the clip's ending) was treated (run e31aa5e7, then 8035e541);
   and what she said was untreated — «toward the subject», «turning fully toward her» — were
   the camera move's fixed sentence and the beat's action, words the motion layer keeps, so
   his second rewrite could not treat them and nothing turned to the picture. Now each of
   quality control's findings has an id (`review_findings`), every finding of her review cites
   one and every id is answered (`review_schema`); her own observations are advisory; each
   finding has a severity and only a serious one left untreated refuses the rewrite (a minor
   defect is accepted); an untreated finding names the field he must change or says the words
   are locked on this layer, quoted from what the layer keeps (`layer_terms`). When every
   finding that refuses the rewrite is locked, he is not asked again on that layer: a motion
   rewrite returns ``layer_exhausted`` and the picture's turn comes (`rewrite_failed_scene`,
   `runbook.stages`), as it does when his second rewrite gives the stored or refused words.
   Every writer reads the studio's lessons for the film's kind whole, before the film's data
   is fitted (`prompt_agent.fit_with_lessons`), and a rewrite whose words break a CONFIRMED
   lesson misses (an unverified one broken is advisory).
8. Nothing is bought on a rewrite that treats nothing, and a lock is only what no field of
   the layer can change (2026-10-12 evening review of a50407e). When she rates every one of
   quality control's findings minor, the take is acceptable as it is: nothing is stored or
   bought and the caller hands the take to her second look (``accepted_minor``). A finding the
   bible's hard limits name (a face where faces are forbidden, writing, panels, «încalcă
   biblia») is serious whatever she says, and within a rung a finding keeps the highest
   severity it was given. A lock quotes at least three words of meaning the rewritten prompts
   say; words a field he may change chose (the move's own sentence, the people rule) are his
   to change, not a lock; a lock in the picture's words turns the motion to the picture, a
   lock only in the composer's own sentences is a tool's defect — one note for the developer
   per scene, nothing bought, the take to her second look (``composer_locked``) — and the
   ladder does not ask the same scene again until something changes (`scene_waits`).
   Quality control's findings are read from its whole refusal, split before any cut; her
   repair proposals, her second look's words and the studio's notes are context, not
   findings.

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

import hashlib
import json
import logging
import re
from collections.abc import Sequence
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
from app.media.markings import markings_kept, markings_note, planned_markings, still_exclusions
from app.media.models import SceneTake, Storyboard, StoryboardScene
from app.media.visual_policy import POLICY_NOTE
from app.models import DomainEvent
from app.services import append_event

logger = logging.getLogger("studio.scene_rewrite")

#: The Director's brief for one scene: {scene_index, layer, diagnosis, avoid, keep, change,
#: summary_ro, failures, run_id, message_id}, and how her review of the rewrite ended
#: (review_verdict, cause, lesson, review_findings, review_attempts, qc_findings, observations,
#: layer_exhausted; `_record_brief`).
BRIEF_EVENT = "media.director_scene_brief"
#: The reason a `SCENE_PROMPTS_REWRITTEN_EVENT` carries when her brief rewrote the scene.
REWRITE_REASON = "director_brief"
#: Who decided a rewrite, as `scene_memory` reads it.
DECIDED_BY = "director"
BRIEF_TASK = "director_scene_brief"
BRIEF_TEMPLATE = "director-scene-brief-v5"
REWRITE_TASK = "scene_prompt_rewrite"
REWRITE_TEMPLATE = "scene-prompt-rewrite-v8"
#: Her review of his rewrite against the findings, before anything is bought on it.
REVIEW_TASK = "director_rewrite_review"
REVIEW_TEMPLATE = "director-rewrite-review-v7"
TREATS, MISSES = "TREATS", "MISSES"
#: Her review when every one of quality control's findings is minor (2026-10-12 evening review
#: of a50407e: a rewrite that treated nothing was stored and bought because each finding was
#: minor). The take is acceptable as it is: nothing is stored or bought, no lesson is drawn,
#: and the caller hands the take to her second look (``accepted_minor``).
ACCEPTED_MINOR = "ACCEPTED_MINOR"
#: His rewrites in one rung: the first, and one more with her review's words when it missed a
#: finding (2026-10-12, f06808c9 scenes 3, 4, 7: a refused rewrite ended the rung, and the next
#: rung asked the same brief again).
REWRITES_PER_RUNG = 2
# Two refused rungs on unchanged source words without a newer failed take are not
# progress. Stop repeated Sarah/Kael tokens; wait for a real change or second look.
MAX_UNCHANGED_REFUSED_RUNGS = 2
#: How serious a finding her review leaves untreated is (Owner, 2026-10-12: «DIRECTOAREA
#: ACCEPTĂ DEFECTELE MICI!»): only a serious one refuses the rewrite.
MINOR: Literal["minor"] = "minor"
SERIOUS: Literal["serious"] = "serious"
#: The length her review is asked to keep a lesson to; the store refuses one longer than its
#: own limit (`prompt_agent.record_prompt_lesson`), never cuts it.
LESSON_CHARS_ASKED = 2400
#: The scope a lesson is kept under (`prompt_agent.record_prompt_lesson`): the serial's prompts
#: are composed, a factual film's compiled, and a rule for one is not always one for the other.
SERIAL_SCOPE, FACTUAL_SCOPE = "serial", "factual"
LAYERS: tuple[str, ...] = ("motion", "still")
MOTION, STILL = LAYERS
#: The refusals of quality control the Director answers with a rewrite.
STILL_GATE_CODE = "LOCAL.STILL_GATE"
QUALITY_CODES: tuple[str, ...] = ("QC.CLIP", STILL_GATE_CODE)
# A terminal request with no delivered clip is the Director's delivery work, not visual QC.
DELIVERY_CODES: tuple[str, ...] = ("RUNPOD.EXPIRED_UNDELIVERED",)
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
#: The briefs older than the ones shown whole are shown in short: the newest this many, each
#: diagnosis at most this long (2026-10-12 review: the list grew with the scene's history and
#: pushed the payload past its budget).
MAX_OLDER_BRIEFS = 12
OLDER_DIAGNOSIS_CHARS = 200
#: The findings of quality control one rewrite answers, each by its id.
MAX_PAYLOAD_CHARS = 140000
#: What the still gate writes beside its findings that is no finding about the picture, read
#: on the whole piece before anything is cut (2026-10-12 review: a cut «Verdictu» slipped past).
_NOT_A_FINDING: tuple[str, ...] = ("verdictul modelului de vedere",)
#: How many findings one refusal keeps, each at most this long once split.
REASON_CHARS = 400
#: A piece of a refusal shorter than this many words is the tail of the one before it (a
#: «prag 15%)» split off its sentence), joined back.
MIN_FINDING_WORDS = 3
#: The studio's own notes beside the film's findings that `fix_check.PROCESS_NOTES` does not
#: hold yet: `runbook.stages.LAYER_EXHAUSTED_NOTE` (d4335c6) rode as a QC finding with an id.
_PROCESS_NOTES: tuple[re.Pattern[str], ...] = (
    re.compile(r"^what was found in this scene cannot be fixed by the movement", re.IGNORECASE),
)
#: The words a redo's reasons carry that are context for her brief, never a finding: her own
#: second look before the purchase (`runbook.stages`, «Directoarea a privit din nou scena: …»).
_CONTEXT_PREFIXES: tuple[str, ...] = ("directoarea a privit din nou scena",)
#: Quality control's words for what the bible's hard limits forbid (`fix_check.HARD_LIMITS`:
#: faces where forbidden, writing, panels; and a picture that breaks the bible): a finding
#: that says them is serious whatever her review says (2026-10-12 evening review: «text
#: lizibil» could be rated minor and the rewrite stored on it).
HARD_LIMIT_WORDS = re.compile(
    r"interzice fețele|text lizibil|apare text|readable text|garbled text|"
    r"lettering|panour\w*|colaj|ecran împărțit|bandă goală|\bpanels?\b|collage|"
    r"split[- ]screen|o singură fotografie|încalcă biblia|breaks the bible|"
    r"faces? (?:are |is )?forbidden",
    re.IGNORECASE,
)
#: The same words, split: writing alone is no hard limit when the plan names an object that
#: carries its own markings (`markings.planned_markings`; the Owner, 2026-10-13, the Kelvin
#: film's thermometer refused for the digits of its scale), the rest always is.
_WRITING_LIMIT = re.compile(
    r"text lizibil|apare text|readable text|garbled text|lettering", re.IGNORECASE
)
_OTHER_LIMITS = re.compile(
    r"interzice fețele|panour\w*|colaj|ecran împărțit|bandă goală|\bpanels?\b|collage|"
    r"split[- ]screen|o singură fotografie|încalcă biblia|breaks the bible|"
    r"faces? (?:are |is )?forbidden",
    re.IGNORECASE,
)
#: A face named in quality control's words: a hard limit when the bible forbids faces. Only
#: the Romanian «chip» with its endings: a bare «chip» is the English word (a microchip film).
_FACE_WORDS = re.compile(
    r"\bfa[țţt][ăa]\b|\bfe[țţt]e(?:le|lor)?\b|\bfaces?\b|\bchip(?:ul|ului|uri|urile|urilor)\b",
    re.IGNORECASE,
)
#: Where a lock's quoted words live (`lock_texts`): the picture's words, which the still layer
#: rewrites (on a motion rewrite: the motion's turn is over, the picture's comes); or the
#: composer's own sentences and the plan's fixed facts, which no layer of a rewrite changes.
LOCK_PICTURE, LOCK_COMPOSER = "picture", "composer"
#: A lock quotes at least this many words of meaning (2026-10-12 evening review: «the», «a»
#: and «toward the subject» were accepted as locks and turned the scene to a paid still).
MIN_QUOTE_WORDS = 3
_QUOTE_FILLER = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "from", "into", "onto", "its", "his",
        "her", "their", "are", "was", "were", "has", "have", "not", "but", "all", "out",
        "over", "under", "off", "who", "while", "one", "each", "than", "very", "just",
        "it", "on", "in", "at", "to", "of", "by", "as", "or", "an", "is", "be", "so",
    }
)  # fmt: skip
#: A cause written into the reasons a redo hands `rewrite_for_redo` (the Director's verdict on
#: the film's finding: why the defect appeared), on its own or after the finding it explains.
_CAUSE_LABEL = re.compile(r"(?:^|[\s(;—–-])(?:cauza|cauză|cause)\s*:\s*", re.IGNORECASE)
#: Where one sentence ends and the next begins, for the diff her review reads.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class SceneBrief(BaseModel):
    """The Director's brief to the Video Editor for one scene quality control refused."""

    model_config = ConfigDict(extra="ignore")
    action: Literal["rewrite", "retry_delivery"] = "rewrite"
    diagnosis: str = Field(min_length=1, max_length=800)
    layer: Literal["motion", "still"]
    avoid: list[str] = Field(min_length=1)
    keep: list[str] = Field(default_factory=list)
    change: list[str] = Field(min_length=1)
    summary_ro: str = Field(min_length=1, max_length=500)
    editorial_visual_intent: str = ""

    @field_validator("layer", "action", mode="before")
    @classmethod
    def _lower(cls, value: Any) -> Any:
        return str(value).strip().lower() if isinstance(value, str) else value

    @field_validator("avoid", "keep", "change", mode="before")
    @classmethod
    def _items(cls, value: Any) -> Any:
        items = value if isinstance(value, list) else [value] if value else []
        return [" ".join(str(item).split()) for item in items if str(item).strip()]


def brief_schema(allowed: tuple[str, ...], *, delivery: bool = False) -> type[SceneBrief]:
    """Her brief bound to the layers this scene may be redone on."""

    class BoundBrief(SceneBrief):
        action: Literal["rewrite", "retry_delivery"] = Field(default=... if delivery else "rewrite")

        @model_validator(mode="after")
        def _allowed(self) -> BoundBrief:
            if self.layer not in allowed:
                raise ValueError(f"layer {self.layer} is not open for this scene: {allowed}")
            if (self.action == "retry_delivery") != delivery:
                raise ValueError(
                    "A terminal delivery failure requires action retry_delivery; a visual "
                    "quality refusal requires a reviewed rewrite, never a delivery retry."
                )
            return self

    return BoundBrief


def _said_text(value: Any) -> str:
    return " ".join(str(value).split()) if value is not None else ""


class FindingReview(BaseModel):
    """One finding of quality control, by its id, and whether the rewrite treats it.

    2026-10-12, f06808c9 scene 7 (runs e31aa5e7, 8035e541): her review listed two diagnoses of
    her own as findings and refused the rewrite while quality control's one finding — the
    clip's ending — was treated. A finding is now one of quality control's, named by the id
    the review's data gives it (`review_findings`); what she notices beyond them is an
    observation (`RewriteReview.observations`) and decides nothing."""

    model_config = ConfigDict(extra="ignore")
    id: int
    #: Her few words for the finding; the record keeps quality control's own words beside them.
    finding: str = Field(default="", max_length=400)
    treated: bool
    #: serious: quality control would refuse the picture or clip again for it, or it breaks the
    #: bible; minor: a small defect the studio accepts (Owner, 2026-10-12).
    severity: Literal["minor", "serious"]
    #: Which prompt the defect lives in; the rewrite's layer when she does not say.
    layer: Literal["still", "motion"] | None = None
    #: The new sentence that treats it; empty for a finding left untreated.
    by: str = Field(default="", max_length=500)
    #: For a finding left untreated, why: what in the rewritten prompts still invites it, or
    #: what is missing. The Video Editor's second rewrite is given exactly these words
    #: (2026-10-12, f06808c9 scenes 3, 4, 7: a refusal nobody explained was asked again).
    why_not: str = Field(default="", max_length=400)
    #: For a finding left untreated: the field of this layer he must change (`layer_terms`) …
    field: str = Field(default="", max_length=40)
    #: … or, when the words that invite it are ones this layer cannot change (a fixed sentence
    #: of the composer, a field kept word for word, the still kept on a motion rewrite), locked
    #: with those words quoted exactly (2026-10-12, f06808c9 scenes 3, 4, 7: «turning fully
    #: toward her» was the beat's action, kept word for word by the motion layer).
    locked: bool = False
    locked_words: str = Field(default="", max_length=300)
    #: Where the locked words live (`LOCK_PICTURE`, `LOCK_COMPOSER`): read by the studio from
    #: the words themselves (`review_schema`), never taken from her answer.
    lock_kind: str = ""

    @field_validator("id", mode="before")
    @classmethod
    def _number(cls, value: Any) -> Any:
        if isinstance(value, str):
            digits = re.sub(r"\D", "", value)
            return int(digits) if digits else value
        return value

    @field_validator("severity", "layer", "field", mode="before")
    @classmethod
    def _word(cls, value: Any) -> Any:
        return str(value).strip().lower() if isinstance(value, str) else value

    @field_validator("finding", "by", "why_not", "locked_words", mode="before")
    @classmethod
    def _text(cls, value: Any) -> Any:
        return _said_text(value)

    @model_validator(mode="after")
    def _explained(self) -> FindingReview:
        if self.treated and not self.by:
            raise ValueError(
                f"finding {self.id} is treated: quote the new sentence that treats it (by)"
            )
        if not self.treated and not self.why_not:
            raise ValueError(f"finding {self.id} is untreated: say why it is not (why_not)")
        if not self.treated and self.locked and not self.locked_words:
            raise ValueError(
                f"finding {self.id} is locked: quote the words this layer keeps that invite it "
                "(locked_words)"
            )
        return self


class BrokenLesson(BaseModel):
    """A lesson of the studio's the rewritten words break, why, and the field to change.

    ``confirmed`` is the studio's reading, never hers: whether the lesson she names is one a
    picture has proven (`review_schema`). Only a confirmed lesson broken refuses a rewrite; an
    unverified one is advisory (2026-10-12 evening review of a50407e: a guess no picture had
    proven yet could refuse every rewrite after it)."""

    model_config = ConfigDict(extra="ignore")
    lesson: str = Field(min_length=1, max_length=400)
    why_not: str = Field(min_length=1, max_length=400)
    field: str = Field(default="", max_length=40)
    confirmed: bool = False

    @field_validator("lesson", "why_not", mode="before")
    @classmethod
    def _text(cls, value: Any) -> Any:
        return _said_text(value)

    @field_validator("field", mode="before")
    @classmethod
    def _word(cls, value: Any) -> Any:
        return str(value).strip().lower() if isinstance(value, str) else value


class RewriteReview(BaseModel):
    """The Director's review of the Video Editor's rewrite against quality control's findings.

    A finding is treated only when the new prompt changes the words that invited it or names,
    in their place, what the scene asks for. The verdict is not hers to state: it is read from
    her findings — ACCEPTED_MINOR when no finding is serious (the take is acceptable as it is:
    nothing is bought on a rewrite, 2026-10-12 evening review); MISSES while a SERIOUS finding
    is untreated, his words break a CONFIRMED lesson of the studio's (``broken_lessons``), or
    nothing at all is treated; TREATS otherwise, a minor finding left untreated included and
    accepted (Owner, 2026-10-12: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI!»). ``cause`` is what in
    the old words invited the defect, ``lesson`` the general rule that keeps it out of every
    future prompt, empty when the defect teaches none («trebuie să înțeleagă de ce apar
    defectele și la viitoarele prompturi să se asigure că nu mai sunt»)."""

    model_config = ConfigDict(extra="ignore")
    findings: list[FindingReview] = Field(min_length=1)
    #: What she notices beyond quality control's findings: recorded, advisory, never decides.
    observations: list[str] = Field(default_factory=list, max_length=6)
    broken_lessons: list[BrokenLesson] = Field(default_factory=list, max_length=6)
    reason_ro: str = Field(min_length=1, max_length=500)
    cause: str = Field(min_length=1, max_length=400)
    #: Never cut by the schema (a cut rule is obeyed as written): one longer than the store
    #: keeps is refused there and the review stands.
    lesson: str = Field(default="", max_length=2000)

    @field_validator("cause", "lesson", "reason_ro", mode="before")
    @classmethod
    def _said(cls, value: Any) -> Any:
        return _said_text(value) if isinstance(value, str) else value

    @field_validator("observations", mode="before")
    @classmethod
    def _observed(cls, value: Any) -> Any:
        items = value if isinstance(value, list) else [value] if value else []
        said: list[str] = []
        for item in items:
            if isinstance(item, dict):
                item = item.get("observation") or item.get("text") or item.get("finding") or ""
            text = _said_text(item)
            if text:
                said.append(text)
        return said

    @property
    def blocking(self) -> list[FindingReview]:
        """The findings that refuse the rewrite: serious, and untreated."""
        return [item for item in self.findings if not item.treated and item.severity == SERIOUS]

    @property
    def refusing_lessons(self) -> list[BrokenLesson]:
        """The broken lessons that refuse the rewrite: the confirmed ones."""
        return [item for item in self.broken_lessons if item.confirmed]

    @property
    def verdict(self) -> str:
        if not any(item.severity == SERIOUS for item in self.findings):
            return ACCEPTED_MINOR
        if self.blocking or self.refusing_lessons:
            return MISSES
        if not any(item.treated for item in self.findings):
            return MISSES
        return TREATS


def _quoted(text: str) -> str:
    """Words as a quote is compared: case, spacing and the quote marks around them dropped."""
    said = " ".join(str(text or "").split()).casefold()
    return said.strip(" \"'«»“”‘’.,;:")


def words_kept(quote: str, kept: Any) -> bool:
    """Whether ``quote`` — words her review says this layer keeps — is in one of the texts
    ``kept``, read as a quote: case and spacing aside, an ellipsis standing for the words
    between its parts."""
    parts = [_quoted(part) for part in re.split(r"\.\.\.|…", str(quote or ""))]
    parts = [part for part in parts if part]
    if not parts:
        return False
    texts = [" ".join(str(text or "").split()).casefold() for text in kept or ()]
    return any(all(part in text for part in parts) for text in texts)


def quote_words(quote: Any) -> int:
    """How many words of meaning a quote says: words of three letters or more that are not
    the glue of a sentence (`MIN_QUOTE_WORDS`)."""
    words = re.findall(r"[^\W\d_]+", _quoted(str(quote or "").replace("…", " ")))
    return len([word for word in words if len(word) >= 3 and word not in _QUOTE_FILLER])


def lesson_confirmed(said: Any, lessons: Any) -> bool:
    """Whether the lesson her review names is one of ``lessons`` (as `prompt_lessons` gave
    them) that a picture has proven: the closest of them, by `prompt_agent.lesson_overlap`
    either way, at least `LESSON_OVERLAP`, and not marked unverified. A lesson she names that
    is none of them, or an unverified one, is advisory."""
    from app.media.prompt_agent import (  # noqa: PLC0415 - it imports us
        LESSON_OVERLAP,
        UNVERIFIED_SUFFIX,
        lesson_overlap,
    )

    text = _norm(said)
    if not text or text.endswith(UNVERIFIED_SUFFIX.strip()):
        return False
    best, proven = 0.0, False
    for lesson in lessons or ():
        given = _norm(lesson)
        provisional = given.endswith(UNVERIFIED_SUFFIX.strip())
        plain = given.removesuffix(UNVERIFIED_SUFFIX.strip()).strip()
        share = (
            1.0
            if _quoted(plain) == _quoted(text)
            else max(lesson_overlap(text, plain), lesson_overlap(plain, text))
        )
        if share > best:
            best, proven = share, not provisional
    return best >= LESSON_OVERLAP and proven


def review_schema(
    ids: tuple[int, ...],
    editable: tuple[str, ...],
    locks: dict[str, Any],
    *,
    serious: Any = (),
    lessons: Any = (),
) -> type[RewriteReview]:
    """Her review bound to this rewrite: every one of quality control's findings (``ids``)
    answered once, no other; an untreated finding names a field he may change on this layer
    (``editable``) or is locked on words this layer keeps — a lock no quote supports would turn
    the scene to the picture, and buy one, on her word alone.

    ``locks`` (`lock_texts`) is where a lock's quote is read: it must say at least
    `MIN_QUOTE_WORDS` words of meaning that the rewritten prompts say (``said``); in the
    composer's own sentences or the plan's fixed facts (``constants``) it is `LOCK_COMPOSER`,
    in the picture's words a motion rewrite keeps (``picture``) `LOCK_PICTURE`; words a field
    he may change chose (``fields``: the move's own sentence, the people rule) are no lock —
    that field is his to change (2026-10-12 evening review of a50407e: her lock on the chosen
    move's sentence alone turned the scene to a paid still). ``serious``: the ids that are
    serious whatever she says (the bible's hard limits, `HARD_LIMIT_WORDS`, and what an
    earlier round of the rung found serious). ``lessons``: the lessons she was given; a broken
    one refuses only when confirmed (`lesson_confirmed`) and then names a field he may change."""
    said = tuple(locks.get("said") or ())
    constants = tuple(locks.get("constants") or ())
    picture = tuple(locks.get("picture") or ())
    chosen = {str(name): tuple(texts) for name, texts in (locks.get("fields") or {}).items()}
    anchored = {int(number) for number in serious or ()}
    given = tuple(lessons or ())

    def lock_of(item: FindingReview) -> str:
        """The lock's kind, or a ValueError saying why it is no lock."""
        quote = item.locked_words
        if quote_words(quote) < MIN_QUOTE_WORDS:
            raise ValueError(
                f"finding {item.id} is locked, but «{quote[:80]}» is not {MIN_QUOTE_WORDS} words "
                "of meaning: quote the kept words that invite it exactly, at least "
                f"{MIN_QUOTE_WORDS} of them, or name the field he must change"
            )
        if not words_kept(quote, said):
            raise ValueError(
                f"finding {item.id} is locked, but «{quote[:80]}» is not in the rewritten "
                "prompts (prompts_after); quote the words exactly as they say them, or name "
                "the field he must change"
            )
        if words_kept(quote, constants):
            return LOCK_COMPOSER
        if words_kept(quote, picture):
            return LOCK_PICTURE
        for name, texts in chosen.items():
            if words_kept(quote, texts):
                raise ValueError(
                    f"finding {item.id}: {name} is his to change — «{quote[:80]}» are the "
                    f"words the {name} he chose says, and another choice says others "
                    "(camera_move_sentences gives every move's words); name field "
                    f"{name} instead of a lock"
                )
        raise ValueError(
            f"finding {item.id} is locked, but «{quote[:80]}» is not in the words this layer "
            "keeps (this_layer); quote them exactly, or name the field he must change"
        )

    class BoundReview(RewriteReview):
        @model_validator(mode="after")
        def _bound(self) -> BoundReview:
            answered = [item.id for item in self.findings]
            twice = sorted({number for number in answered if answered.count(number) > 1})
            if twice:
                raise ValueError(f"findings answer id {twice} more than once; answer each once")
            unknown = sorted(set(answered) - set(ids))
            if unknown:
                raise ValueError(
                    f"findings name ids quality control did not give: {unknown}; findings are "
                    f"only quality control's ({list(ids)}), your own go to observations"
                )
            missing = sorted(set(ids) - set(answered))
            if missing:
                raise ValueError(f"every finding of quality control is answered: missing {missing}")
            for item in self.findings:
                # A hard limit of the bible, or what an earlier round found serious, stays
                # serious (2026-10-12 evening review: round 2 downgraded round 1's serious).
                if item.id in anchored:
                    item.severity = SERIOUS
                item.lock_kind = ""
                if item.treated:
                    continue
                if item.locked:
                    item.lock_kind = lock_of(item)
                elif item.field not in editable:
                    raise ValueError(
                        f"finding {item.id} is untreated: field must be one he may change on "
                        f"this layer ({', '.join(editable)}), or say locked with the words"
                    )
            for broken in self.broken_lessons:
                broken.confirmed = lesson_confirmed(broken.lesson, given)
                if broken.confirmed and broken.field not in editable:
                    raise ValueError(
                        f"a broken lesson names the field he must change ({', '.join(editable)})"
                    )
            return self

    return BoundReview


def shot_schema(
    index: int,
    layer: str,
    *,
    serial: bool = False,
    editor_final: bool = False,
    migrating: bool = False,
) -> type[BaseModel]:
    """The editor's one shot, fitted to the shot schema (`prompt_agent._coerce`), and holding
    what the layer rewrites: a motion for the motion layer, the picture and its motion for the
    still layer. A serial shot is composed from fewer fields (`SERIAL_STILL_FIELDS`,
    `SERIAL_MOTION_FIELDS`): its still layer must give the action, its motion layer a camera
    move, an ending frame or a feeling."""
    if editor_final:
        # Vendor prose is neither a legacy plan nor input for its shape coercer.
        class FinalSceneShot(BaseModel):
            model_config = ConfigDict(extra="ignore")
            scene_index: int = Field(default=index, ge=1, le=120)
            camera_move: str = Field(strict=True, min_length=1)
            motion_prompt: str = Field(strict=True, min_length=1)
            still_prompt: str = Field(default="", strict=True)
            negative_prompt: str | None = Field(default=None, strict=True)

            @model_validator(mode="before")
            @classmethod
            def _this_scene(cls, data: Any) -> Any:
                if not isinstance(data, dict):
                    return data
                if not any(name in data for name in ("still_prompt", "motion_prompt")):
                    for key in ("shot", "shots"):
                        inner = data.get(key)
                        if isinstance(inner, list) and inner:
                            inner = inner[0]
                        if isinstance(inner, dict):
                            data = inner
                            break
                return {**data, "scene_index": index}

            @model_validator(mode="after")
            def _rewrites(self) -> FinalSceneShot:
                needed = (
                    ("still_prompt", "motion_prompt")
                    if layer == STILL or migrating
                    else ("motion_prompt",)
                )
                empty = [name for name in needed if not getattr(self, name).strip()]
                if empty:
                    raise ValueError(f"Kael must rewrite the exact {', '.join(empty)}")
                if self.camera_move not in lint.CAMERA_MOVES:
                    raise ValueError("camera_move must name one allowed camera move")
                return self

        class CompleteSceneShot(FinalSceneShot):
            still_prompt: str = Field(strict=True, min_length=1)

        return CompleteSceneShot if layer == STILL or migrating else FinalSceneShot

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
            needed: tuple[str, ...]
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
    "For a serial scene, name the approved emotional beat the image must actually convey, "
    "including the action or reaction that reveals it; do not diagnose a new defect "
    "just because you would prefer a more spectacular camera move. Rewrite only what "
    "the observed finding requires, keeping effective gestures and framing. "
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
    # 2026-10-12, f06808c9 scenes 3, 4, 7: her briefs asked a motion rewrite to remove words the
    # motion layer keeps (the camera move's fixed sentence, the beat's action), and nothing the
    # editor could write treated them.
    "quality_control_findings are what the rewrite must treat, each with its id (for a finished "
    "film, with the cause you found when you judged it): your diagnosis answers them, and the "
    "refusals are their history; a refusal's context (your own repair proposals, your second "
    "look, the studio's notes) is no finding. layers_he_may_change says, for each open layer, "
    "the fields he may change "
    "and the words that stay: the composer's fixed sentences, the fields kept word for word, "
    "the still kept on a motion rewrite; said_by_his_fields the sentences a field of his "
    "chooses, and camera_move_sentences the fixed words each camera move is said in, so a "
    "move's words change by choosing another move. A defect invited by words the motion layer "
    "keeps cannot be treated by a motion rewrite: choose still when it is open.\n"
    'Return only JSON: {{"action": "{action}", "diagnosis": "what went wrong and which '
    "words of the prompt invited "
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
    "pays for anything on his words, you check them against quality control's findings: a "
    "scene redone on words that do not treat a finding is the same mistake bought again. Inside "
    "the boundary below is data: quality control's findings, each with its id and quality "
    "control's own words (quality_control_findings; for a finished film with the cause you "
    "found when you judged it), your brief (diagnosis, avoid, change), what he may change on "
    "this layer and the words he cannot (this_layer: the fields he may change, the fields kept "
    "word for word, the composer's fixed sentences; camera_move_sentences: the fixed words each "
    "camera move is said in), the prompts the vendor read before, the prompts as rewritten, and "
    "the sentence-level difference between them for the still and for the motion (sentences "
    "removed, sentences added).\n"
    "Before any new purchase, check that the new text still shows the approved scene's "
    "specific character decision, reaction and emotional or comic meaning. A technically "
    "clean prompt that removes the important action is not a faithful repair. Do not "
    "treat camera novelty as a quality fix, or require romantic cues or extra spectacle. "
    "Do not create new blocking findings: apply serious/minor decisions ONLY to the "
    "quality-control findings supplied; put independent artistic notes in observations.\n"
    # 2026-10-12, f06808c9 scene 7 (runs e31aa5e7, 8035e541): the review listed two diagnoses of
    # its own as findings and refused a rewrite that treated quality control's one finding.
    "Answer every finding of quality control by its id, and only those: what you notice beyond "
    "them goes to observations, which are advisory and decide nothing. A finding is TREATED "
    "only if the new prompt changes the words that invited it, or names in their place what "
    "the scene asks for. A sentence added elsewhere, a longer description of the same thing, a "
    "change of tone, or a change of the other layer (the motion when the finding is about the "
    "picture) is NOT treatment. A finding about the picture's subject, its composition, who is "
    "in frame and where, or its location is answered in the still prompt; a finding about the "
    "movement, the camera's path or the clip's ending in the motion prompt. The clip's camera "
    "sentence is the fixed sentence of its move with its path and tempo (camera_move_sentences); "
    "a lens, a framing distance or a shot size belongs to the picture and is never a motion "
    "finding. For each finding "
    "say whether it is treated and quote the new sentence of the rewritten prompts that treats "
    "it (by); its layer (still or motion: the prompt the defect lives in); and its severity: "
    "serious when quality control would refuse the picture or the clip again for it, or it "
    "breaks the bible (a face where faces are forbidden, writing, panels, the wrong subject — "
    "these are serious whatever else you weigh), minor when it is small and the studio accepts "
    "it (Owner, 2026-10-12: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI!»). When every finding is "
    "minor, the take is accepted as it is and nothing is bought on the rewrite. For a finding "
    "left untreated say why (why_not) — which words of the rewritten prompts still invite it, "
    "or what they fail to name; he rewrites once more from exactly these words — and either "
    "name the field he must change (field, one of this_layer's fields_he_may_change) or, when "
    "the words that invite it are ones this layer cannot change (this_layer's fixed_sentences, "
    "a field kept word for word, the still kept on a motion rewrite), say locked: true and "
    "quote those words exactly as the rewritten prompts say them, at least three words of "
    "meaning (locked_words). Words a field of his chose (this_layer's said_by_his_fields: the "
    "camera move's own sentence, the people rule) are never locked: a finding they invite is "
    "treated by choosing differently, so name that field. The rewrite is refused while any "
    "serious finding is untreated; a minor one left untreated does not refuse it.\n"
    # Owner, 2026-10-12: «trebuie să înțeleagă de ce apar defectele și la viitoarele prompturi
    # să se asigure că nu mai sunt».
    "Then say why the defect appeared (cause): in one sentence, which words of the prompts "
    "before invited it. And write the lesson: one general rule for writing every future prompt "
    "so this kind of defect does not appear again — phrased positively (what to write, not what "
    "to avoid), at most {lesson_chars} characters, with no film title, no scene number, no id "
    "and no person's name, unless the rule is about the office serial's recurring characters; "
    "leave it empty when the defect teaches no general rule.\n"
    'Return only JSON: {{"findings": [{{"id": 1, "finding": "the finding in a few words", '
    '"treated": true | false, "by": "the new sentence that treats it, or empty", "severity": '
    '"minor" | "serious", "layer": "still" | "motion", "why_not": "for an untreated finding, '
    'why it is not treated; empty when treated", "field": "the field he must change, or '
    'empty", "locked": false, "locked_words": "the kept words that invite it, when locked"}}], '
    '"observations": ["what you notice beyond the findings"], "broken_lessons": [{{"lesson": '
    '"the lesson", "why_not": "which words break it", "field": "the field to change"}}], '
    '"cause": "which words of the prompts before invited the defect", "lesson": "the general '
    'rule for future prompts, or empty", "reason_ro": "one sentence in Romanian for the Owner: '
    'what is treated and what is not"}}.\n'
)
#: Added to her review when the studio has lessons: words that break one make the same defect
#: again (2026-10-12, the Owner: «la viitoarele prompturi să se asigure că nu mai sunt»).
_REVIEW_LESSONS_NOTE = (
    "Check the rewritten prompts against the studio's lessons too: a rewrite that treats the "
    "findings but whose words break a confirmed lesson is refused; one marked (unverified) "
    "is noted for him and refuses nothing. List each lesson his words break under "
    "broken_lessons, quoted as given, with why and the field he must change; a lesson only "
    "the composer's fixed words break is not his to keep, leave it out.\n"
)
#: Added to her review of his second rewrite in the rung (2026-10-12).
_SECOND_REVIEW_NOTE = (
    "This is his second rewrite in this round: your review of his first one is in the data "
    "(your_earlier_review). Check above all that every finding you found untreated there is "
    "treated now, by the words your why_not named, and answer every finding by its id again; "
    "the rules are the same.\n"
)
#: Added to the Video Editor's second rewrite in the rung, with her review inside a boundary
#: of its own (2026-10-12, f06808c9 scenes 3, 4, 7: «Rescrierea nu tratează constatarea …» and
#: the next round asked the same brief — the refusal's words never reached him; then the words
#: she named were ones his layer keeps, and nothing told him so).
_SECOND_REWRITE_NOTE = (
    "The Director reviewed your rewrite of this shot against quality control's findings and "
    "refused it, so nothing was bought on it. Her review is inside the boundary below: each "
    "finding your rewrite left untreated, why it is not treated (why_not) and the field you "
    "must change; the lessons your words break; which words of the old prompts invited the "
    "defect (cause); the findings you did treat with the sentence that treats them; and your "
    "refused prompts. What you may change on this layer and the words you cannot are in "
    "this_layer and camera_move_sentences above. Write the shot once more, following her brief "
    "and the layer's rule: for every untreated finding change the field she names, exactly the "
    "words her why_not names, or name in their place what the scene asks for; keep the "
    "sentences that already treat a finding; do not send the refused rewrite again.\n"
)
#: Added to his second rewrite when his first, on the still layer, left the picture's words as
#: they were (2026-10-12 evening review of a50407e: such a rewrite was reviewed on the
#: motion's terms, as if the brief had asked for the movement).
_STILL_UNCHANGED_NOTE = (
    "Your rewrite of this shot was on the still layer, but the picture's words did not "
    "change: the still prompt the studio composed from your fields is word for word the one "
    "before, so nothing about the picture is treated and nothing was bought on it. Write the "
    "shot once more and change the fields the picture is said from (this_layer above), as "
    "her brief asks; your refused prompts are inside the boundary below.\n"
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
    "it before, the prompts the vendor read, the reasons quality control gave, her brief, and "
    "what you may change on this layer and the words the studio keeps (this_layer).\n"
    "Rewrite this one shot, following her brief exactly: nothing she lists under avoid may "
    "appear in any field, what she lists under keep stays as it is, what she lists under change "
    "is written differently. {layer}\n"
    "Describe what is seen and what moves, plainly and positively: a generator does not read "
    "'no' or 'without', it draws the word. When the bible says people's faces must not be seen, "
    "show people only from behind, small and distant, or only their hands. Never ask for writing "
    "in the picture. Do not add facts, numbers, dates or events that are not in the narration. "
    "EDITOR_FINAL_v1: Write the complete exact vendor text in the named prompt fields. "
    "No Python composer rewrites your sentences. Legacy planning fields such as subject, "
    "action and motion are source data only, not the answer format. "
    "Choose exactly one camera_move from: {moves}. Choose it for the approved scene's "
    "emotional and narrative purpose, not for arbitrary variety. Static is valid when a "
    "reaction or awkward silence should hold; for a moving camera, describe a clear path "
    "and tempo from start to end, along with the actor's verbs. Name colours in words. "
    "The still_prompt describes "
    "one frozen moment — what is seen, a "
    "pose, a state, a place — with no camera move, no speed and no span of the clip in them: "
    "a still cannot show movement, so everything that moves goes to motion_prompt; "
    "write its path, tempo and ending there. Respect provider_limits and the series look. "
    "Sarah judges precisely this final text, so replace the concrete words she identified "
    "as wrong. Return only JSON with this shot: {response}.\n"
    "Optional negative_prompt is a separate string of exclusions, or null. "
    "Do not replace any required prompt with a draft motion or other planning field.\n"
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


def refusal_findings(reasons: Any) -> list[str]:
    """Quality control's refusal of one take as its findings, read whole before anything is
    cut (2026-10-12 evening review of a50407e: the refusal was cut at 400 characters first and
    split after, so a finding ended «Verdictu» and the gate's verdict line, cut, read as a
    finding): each reason split at the «; » the gate and clip QC join their findings with —
    never inside «…» or (…) — the gate's verdict line and the studio's notes left out
    (`_is_finding`), a piece of fewer than `MIN_FINDING_WORDS` words joined back to the one
    before it. Current findings stay whole; only historical summaries are shortened."""
    pieces: list[str] = []
    for reason in [reasons] if isinstance(reasons, str) else list(reasons or []):
        for piece in _pieces(reason):
            if not _is_finding(piece):
                continue
            if pieces and len(piece.split()) < MIN_FINDING_WORDS:
                pieces[-1] = f"{pieces[-1]}; {piece}"
                continue
            pieces.append(piece)
    return pieces


def scene_failures(session: Session, storyboard_id: str, scene_index: int) -> list[dict[str, Any]]:
    """The scene's takes quality control refused, newest first, each with its findings
    (`refusal_findings`): a clip's from its clip-QC report's blocks, a still's from the gate's
    words."""
    from app.media.assembler import clip_qc_of  # noqa: PLC0415 - a large module

    failures: list[dict[str, Any]] = []
    for row in scene_takes(session, storyboard_id, scene_index):
        if row.status != "REJECTED" or row.failure_code not in QUALITY_CODES:
            continue
        reasons: list[str] = []
        if row.failure_code == "QC.CLIP":
            report = clip_qc_of(session, row.id) or {}
            reasons = refusal_findings([str(item) for item in report.get("blocks_ro") or []])
        if not reasons and row.failure_detail:
            reasons = refusal_findings(str(row.failure_detail))
        failures.append(
            {
                "kind": row.kind,
                "model": row.model_id,
                "at": str(row.created_at or "")[:16],
                "code": row.failure_code,
                "reasons": reasons,
            }
        )
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
            # The motion layer could not treat the finding: the words that invite it are ones
            # it keeps (2026-10-12, f06808c9 scenes 3, 4, 7) — the picture's turn.
            "layer_exhausted": bool(payload.get("layer_exhausted")),
            # Her review refused his rewrite and his second one too: the layer had its rung
            # (2026-10-12 evening review: a motion rung refused twice was asked again forever).
            "refused_twice": refused_twice(payload),
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
            verdict = payload.get("review_verdict")
            brief["review_verdict"] = verdict
            brief["review_reason_ro"] = str(payload.get("review_reason_ro") or "")
            # Why the defect appeared, why a finding stayed untreated, and the rule she drew
            # from it (2026-10-12, f06808c9 scenes 3, 4, 7: the next brief asked the same
            # thing because none of this reached it).
            brief["cause"] = str(payload.get("cause") or "")
            if verdict == TREATS:
                # A brief whose second rewrite treated what the first did not: nothing is left
                # untreated, and the refused round is history of its own (2026-10-12 review:
                # round 1's why_not read as if the scene still carried it).
                brief["why_not"] = []
                brief["refused_rounds"] = refused_rounds(payload)
            else:
                brief["why_not"] = untreated_findings(payload)
            brief["lesson"] = str(payload.get("lesson") or "")
        for flag in ("accepted_minor", "composer_locked"):
            if payload.get(flag):
                brief[flag] = True
        briefs.append(brief)
    return briefs


def refused_twice(payload: dict[str, Any]) -> bool:
    """Whether a brief's rung ended with her review refusing his second rewrite as well: the
    layer was asked twice and could not treat the findings (`open_layers` counts it)."""
    if payload.get("rewritten"):
        return False
    rounds = [item for item in payload.get("review_attempts") or [] if isinstance(item, dict)]
    return len(rounds) >= REWRITES_PER_RUNG and rounds[-1].get("verdict") == MISSES


def _finding_words(item: dict[str, Any]) -> str:
    """A reviewed finding in words: her few words for it, else quality control's."""
    return " ".join(str(item.get("finding") or item.get("qc_text") or "").split())


def _untreated(findings: Any) -> list[dict[str, Any]]:
    """The findings a review left open: untreated, and not a minor one she accepted."""
    said: list[dict[str, Any]] = []
    for item in findings or []:
        if not isinstance(item, dict) or item.get("treated") or item.get("accepted"):
            continue
        finding = _finding_words(item)
        if not finding:
            continue
        entry: dict[str, Any] = {"finding": finding, "why_not": str(item.get("why_not") or "")}
        if item.get("locked"):
            entry["locked"] = True
        said.append(entry)
    return said


def untreated_findings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every finding her reviews of a brief's rewrites left untreated, with why, oldest round
    first and each finding once: from the rounds (``review_attempts``, since 2026-10-12) or
    the last review's findings."""
    rounds = [item for item in payload.get("review_attempts") or [] if isinstance(item, dict)]
    lists = [item.get("findings") or [] for item in rounds] or [payload.get("review_findings")]
    seen: set[str] = set()
    found: list[dict[str, Any]] = []
    for findings in lists:
        for entry in _untreated(findings):
            if entry["finding"].lower() in seen:
                continue
            seen.add(entry["finding"].lower())
            found.append(entry)
    return found


def refused_rounds(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The rounds her review refused in a rung whose last rewrite she passed: each with what
    it left untreated, why, and the cause she gave."""
    return [
        {
            "round": item.get("round"),
            "why_not": _untreated(item.get("findings")),
            "cause": str(item.get("cause") or ""),
        }
        for item in payload.get("review_attempts") or []
        if isinstance(item, dict) and item.get("verdict") == MISSES
    ]


def _cut(text: Any, limit: int) -> str:
    """Compatibility helper: keep complete scene evidence."""
    del limit
    return " ".join(str(text or "").split())


def _brief_in_short(brief: dict[str, Any]) -> dict[str, Any]:
    """An older brief beyond the ones shown whole: its diagnosis (at most
    `OLDER_DIAGNOSIS_CHARS`) and how it ended, so no diagnosis that failed is written again
    however long the scene's history is."""
    short = {
        key: brief.get(key)
        for key in ("at", "layer", "rewritten", "diagnosis", "review_verdict", "cause")
        if brief.get(key) not in (None, "", [])
    }
    for key in ("diagnosis", "cause"):
        if key in short:
            short[key] = _cut(short[key], OLDER_DIAGNOSIS_CHARS)
    return short


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
        attempted = (
            brief.get("rewritten")
            or brief.get("same_prompt")
            or brief.get("layer_exhausted")
            or brief.get("refused_twice")
        )
        if not attempted:
            continue
        # A motion rewrite that landed, one that came back with the same words (the
        # cyclotron's scene 5, 2026-10-12: asked the same every hour), one her review found
        # could not treat the finding on this layer (f06808c9 scenes 3, 4, 7, the same day),
        # or one she refused twice in its rung (the evening review: motion was chosen again
        # without end) is a motion attempt on this picture; a still rewrite starts the count
        # again.
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
        from app.media.production_policy import resolve_storyboard_plan  # noqa: PLC0415

        route = resolve_storyboard_plan(session, board)
        image_route = (route.get("purposes") or {}).get("image") or {}
        video_route = next(
            (
                s.get("video") or {}
                for s in route.get("scenes") or []
                if s["scene_index"] == scene_index
            ),
            {},
        )
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
            "contract": {
                "still_model_id": image_route.get("model_id"),
                "model_id": video_route.get("model_id"),
            },
            "visual_prompt": str(target.visual_prompt or ""),
            "shot_type": target.shot_type,
            "previous_moves": moves,
            "previous_ending": previous_ending,
            "failures": scene_failures(session, storyboard_id, scene_index),
            "briefs": briefs,
            "older_briefs": [],
            "last_code": last_code,
            # The plan's objects that carry their own markings (`markings.planned_markings`):
            # a writing finding about them is hers to rate, never anchored serious.
            "markings": planned_markings(
                package.get("still_prompt") or target.visual_prompt,
                package.get("writer_visual"),
                package.get("subject"),
                package.get("action"),
                package.get("environment"),
                excluded=package.get("avoid") or [],
            ),
            "layers": open_layers(session, storyboard_id, scene_index, last_code=last_code),
            "local_move": _local_move(session, storyboard_id, scene_index),
        }
        # An Owner-approved plan correction outranks older bible orientation. Read its
        # immutable receipt; do not copy a historical provider prompt into the new contract.
        for event in session.scalars(
            select(DomainEvent)
            .where(
                DomainEvent.aggregate_id == storyboard_id,
                DomainEvent.event_type == "media.owner_physical_prompt_repair",
            )
            .order_by(DomainEvent.sequence.desc())
        ):
            payload = event.payload if isinstance(event.payload, dict) else {}
            if payload.get("scene_index") != scene_index:
                continue
            intent = (payload.get("package") or {}).get("writer_visual")
            if isinstance(intent, str) and intent.strip():
                context["editorial_visual_intent"] = (
                    package.get("editorial_visual_intent") or intent
                )
                context["editorial_authority"] = {
                    "event_id": event.event_id,
                    "type": event.event_type,
                    "reason": payload.get("reason"),
                }
            break
        if last_code in DELIVERY_CODES:
            failed = next(
                (
                    take
                    for take in scene_takes(session, storyboard_id, scene_index)
                    if take.failure_code == last_code
                ),
                None,
            )
            if failed is not None:
                context["delivery_failure"] = {
                    "take_id": failed.id,
                    "code": last_code,
                    "kind": failed.kind,
                    "detail": failed.failure_detail or "Furnizorul nu a livrat fișierul.",
                }
                context["layers"] = (STILL if failed.kind == "still" else MOTION,)
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
            "continuity while there is room; on an establishing or wide shot the people are "
            "small figures in the room and no hand-by-hand detail of action, emotion, "
            "background or continuity is said in the picture: what a hand rests on or holds "
            "is said placed before its owner, every other word stays (the clip keeps the whole "
            "action)"
        ),
        "how_the_clip_is_composed": (
            "camera_move with its path and tempo, the whole action as the chain of movement, "
            "the ending frame, the people's faces kept with the expression emotion names, held "
            "from the first frame to the last; the people's gestures only when action and "
            "ending_frame leave them free (a pose held — hands resting, flat or held, «holds», "
            "nothing changed — or an establishing, wide, reaction or narrator shot says none); "
            "the room's flicker and stir only when nothing in lighting, background, "
            "continuity, ending_frame or avoid asks for a steady light or a still room"
        ),
        "composition_limits": {
            "still_max_characters": look.get("max_prompt_chars"),
            "action": (
                "For a still correction, put each person's visible first moment in its own "
                "semicolon-separated clause, before that person's later moments. Example: "
                "Nadia taps the pen against the ledger; Sarah's shoulder and arm only at the "
                "right edge. A correction appended after 'then' in the same clause is dropped "
                "from the still. Keep every required first-frame condition within the route "
                "allowance; an over-limit prompt is held, never truncated. The composer inserts "
                "the canonical hair "
                "and clothes: do not repeat them in action. Use a short named pose/action for "
                "each visible person and ensure subject, cast, first frame and ending agree."
            ),
            "ending_frame": (
                "Describe only the final visible subjects and their framing, concisely. "
                "Do not append camera instructions, zoom/pan paths or a complete motion prompt: "
                "an ending that names a camera move is omitted. The camera move belongs in "
                "camera_move. Example: the same medium close-up on Nadia, Sarah's shoulder "
                "still at the right edge."
            ),
        },
    }


def lesson_scope(context: dict[str, Any]) -> str:
    """The scope of the studio's lessons this scene reads and writes: the serial's, or a
    factual film's (`prompt_agent.record_prompt_lesson`)."""
    return SERIAL_SCOPE if context.get("serial") else FACTUAL_SCOPE


def _norm(text: Any) -> str:
    return " ".join(str(text or "").split())


def _present(sentences: list[str], prompt: str) -> list[str]:
    """Of ``sentences``, those ``prompt`` says, each once, in the order the prompt says them
    (one the word budget left out is not there to blame)."""
    said = _norm(prompt).casefold()
    found: dict[str, int] = {}
    for sentence in sentences:
        text = _norm(sentence)
        if text and text not in found and text.casefold() in said:
            found[text] = said.index(text.casefold())
    return sorted(found, key=found.__getitem__)


def _motion_sentences(context: dict[str, Any], motion: str) -> tuple[list[str], dict[str, list]]:
    """The composer's sentences a motion prompt carries that no field of the shot writes: (the
    constants every layer keeps — the measured move, the faces and the room, the closing —
    and, by the field whose choice says them, the rest: the camera move's own sentence and its
    second beat under ``camera_move``; the world's default motion and the pad under
    ``motion`` for a factual film, ``ending_frame`` for the serial, whose length decides the
    pad)."""
    from app.media import prompt_agent as words  # noqa: PLC0415 - it imports us

    serial = bool(context.get("serial"))
    constants = [words.MEASURED_SENTENCE, words.FACES_CONSTRAINT, lint.MOTION_CLOSING]
    if serial:
        constants[1:1] = [
            words.SERIAL_CAST_TAIL,
            words.SERIAL_FACES_SENTENCE,
            words.SERIAL_LISTEN_TAIL,
        ]
    fixed = _present(constants, motion)
    if lint.MOTION_CLOSING not in fixed:
        fixed += _present([lint.VEO_MOTION_CLOSING], motion)
    # Since 2026-10-16 the serial's life sentence follows the plan (`serial_life_sentence`):
    # a held pose or a steady room in the ending takes its halves out, so it is the
    # ending_frame's sentence — his to change, never a lock (87c05891 scenes 1 and 6: her
    # reviews named «As they speak their hands gesture…» untreated, round after round).
    world = [words.DEFAULT_WORLD_MOTION, words.MOTION_PAD, words.MOTIONLESS_PAD]
    if serial:
        world += list(words.SERIAL_LIFE_SENTENCES)
    chosen = {
        "camera_move": _present(
            [
                *words.MOVE_SENTENCES.values(),
                *words.MOVE_SHORT.values(),
                words.END_BEAT,
                words.MOTIONLESS_END_BEAT,
            ],
            motion,
        ),
        ("ending_frame" if serial else "motion"): _present(world, motion),
    }
    if serial:
        # The plan's expression, named and held, is the emotion field's sentence.
        chosen["emotion"] = [
            sentence
            for sentence in _sentences(motion)
            if sentence.startswith(words.SERIAL_EXPRESSION_LEADS)
        ]
    return fixed, {name: said for name, said in chosen.items() if said}


def _still_sentences(
    context: dict[str, Any], package: dict[str, Any], still: str
) -> tuple[list[str], dict[str, list]]:
    """The composer's sentences a still prompt carries that no field of the shot writes: (the
    constants — the look, and for the serial the room, the fixed framing, the frame and the
    people as their bibles describe them; for a factual film the composition and the
    exclusions — and, under the field whose choice says it, the people rule: ``subject``, since
    who the picture shows decides between `PEOPLE_SENTENCE` and `NO_PEOPLE_SENTENCE`)."""
    from app.media import prompt_agent as words  # noqa: PLC0415 - it imports us
    from app.media.series_look import room_sentence  # noqa: PLC0415

    if context.get("serial"):
        look = context.get("look") or {}
        framing = _serial_shot(context).get("fixed_framing") or ""
        candidates = [
            str(look.get("block") or ""),
            f"Location: {package.get('location')}." if package.get("location") else "",
            # The room's sentence from the look's table: the composer's, not his.
            room_sentence(look, package.get("location")),
            str(framing),
            words.SERIAL_FRAME_SENTENCE,
            words.SERIAL_BLANK_SENTENCE,
        ]
        found = _present(candidates, still)
        found += [
            sentence
            for sentence in _sentences(still)
            if sentence.startswith("In frame, facing the viewer:")
        ]
        return found, {}
    # The exclusions as this scene says them: «No text, no logo.», or the object's own scale
    # kept when the plan names one that carries markings (`markings`, 2026-10-13).
    marked = tuple(context.get("markings") or ())
    candidates = [
        str(package.get("look_block") or ""),
        words.COMPOSITION_SENTENCE,
        still_exclusions(marked),
        markings_kept(marked),
    ]
    people = _present(
        [words.PEOPLE_SENTENCE, words.CLOSE_PEOPLE_SENTENCE, words.NO_PEOPLE_SENTENCE], still
    )
    return _present(candidates, still), ({"subject": people} if people else {})


def _layer_fields(context: dict[str, Any], layer: str) -> tuple[dict[str, str], dict[str, Any]]:
    """(the fields he may change on ``layer``, each with what it becomes; the fields kept word
    for word, with their words)."""
    serial = bool(context.get("serial"))
    stored = context["package"]
    kept: dict[str, Any]
    if serial:
        if layer == MOTION:
            fields = {
                "camera_move": "the clip's one camera move: its sentence opens the motion",
                "ending_frame": (
                    "said in the motion as «The shot ends on …»; a pose it holds or a steady "
                    "room it names takes the people's gestures or the room's flicker out"
                ),
                "emotion": (
                    "the clip's feeling: the expression the faces hold from the first frame to "
                    "the last, said in the motion only"
                ),
            }
            kept = {"action": stored.get("action")}
        else:
            fields = {
                "action": (
                    "its FIRST moment is the still's action (without hand-by-hand detail on an "
                    "establishing or wide shot: what a hand rests on or holds stays, placed "
                    "before its owner); the whole action is the clip's chain of movement, and a "
                    "pose its hands hold («her right hand resting on…», «holds,», «held still») "
                    "takes the people's gestures out"
                ),
                "emotion": (
                    "said in the still, and in the motion as the expression held from the "
                    "first frame to the last"
                ),
                "background": "said in the still while there is room",
                "continuity": "said in the still while there is room",
                "ending_frame": "said in the motion as «The shot ends on …»",
                "camera_move": "the clip's one camera move: its sentence opens the motion",
            }
            kept = {
                "in_frame": [
                    person.get("name")
                    for person in stored.get("in_frame") or []
                    if isinstance(person, dict)
                ],
                "location": stored.get("location"),
                "shot_size": stored.get("shot_size"),
            }
    elif layer == MOTION:
        fields = {
            "motion": "its clauses are said in the motion prompt",
            "camera_move": "the clip's one camera move: its sentence opens the motion",
            "ending_frame": "the final visible state, said in this clip; no camera instructions",
        }
        kept = {name: stored.get(name) for name in ("subject", "action", "environment")}
    else:
        said = {
            "subject": "said first in the still; who it shows chooses the people rule",
            "action": "said in the still; its verbs of motion are said in the clip too",
            "environment": "said in the still; its moving world may open the clip",
            "camera": "its framing is the still's frame",
            "lighting": "said in the still",
            "motion": "its clauses are said in the motion prompt",
            "camera_move": "the clip's one camera move: its sentence opens the motion",
            "ending_frame": "the final visible state, said in this clip; no camera instructions",
        }
        fields = {
            name: said.get(name, "kept on the shot; not said in the prompts")
            for name in SHOT_FIELDS
            if name != "avoid"
        }
        kept = {}
    return fields, {name: value for name, value in kept.items() if value not in (None, "", [])}


def _flat(values: Any) -> list[str]:
    texts: list[str] = []
    for value in values:
        texts.extend(str(item) for item in (value if isinstance(value, list) else [value]))
    return [text for text in texts if text.strip()]


def _layer_words(
    context: dict[str, Any],
    layer: str,
    package: dict[str, Any] | None,
    visual: str | None,
) -> dict[str, Any]:
    """The prompts as stored or, given ``package`` and ``visual``, as rewritten, read once for
    `lock_texts` and `layer_terms`: the still and the motion, the composer's constants in each,
    the sentences each field of his chooses on ``layer``, and the fields of the layer."""
    stored = context["package"]
    package = package if package is not None else stored
    still = visual if visual is not None else str(stored.get("still_prompt") or "")
    still = still or str(context.get("visual_prompt") or "")
    motion = str(package.get("motion_prompt") or "")
    still_fixed, still_chosen = _still_sentences(context, package, still)
    motion_fixed, motion_chosen = _motion_sentences(context, motion)
    fields, kept = _layer_fields(context, layer)
    chosen = {name: list(said) for name, said in motion_chosen.items()}
    if layer != MOTION:
        # On a motion rewrite the people rule is the picture's (the still is kept whole); on
        # the still layer it is said by the subject he chooses.
        for name, said in still_chosen.items():
            chosen.setdefault(name, []).extend(said)
    return {
        "package": package,
        "still": still,
        "motion": motion,
        "still_fixed": still_fixed,
        "motion_fixed": motion_fixed,
        "chosen": {name: said for name, said in chosen.items() if said},
        "fields": fields,
        "kept": kept,
    }


def lock_texts(
    context: dict[str, Any],
    layer: str,
    *,
    package: dict[str, Any] | None = None,
    visual: str | None = None,
) -> dict[str, Any]:
    """Where a locked finding's quote is read (`review_schema`), from the prompts as stored or,
    given ``package`` and ``visual``, as rewritten: {"said": the still and the motion prompt;
    "constants": the composer's sentences no layer of a rewrite changes and, on the still
    layer, the plan's fixed facts (who is in frame, the room, the shot's size); "picture": on
    a motion rewrite, the still it keeps whole and the fields it keeps word for word — words
    the still layer rewrites; "fields": by field he may change, the sentences his choice of it
    says}. 2026-10-12 evening review of a50407e: the chosen move's own sentence and the people
    rule were read as words the layer keeps, so a lock on them turned the scene to a paid
    still although another choice of the field says other words."""
    active = package or context["package"]
    if active.get("prompt_format") == "editor_final_v1" or context.get("final_rewrite"):
        still = str(visual or active.get("still_prompt") or context.get("visual_prompt") or "")
        motion = str(active.get("motion_prompt") or "")
        # No fixed Python sentences exist in editor-final text. Only the still
        # itself is locked during a motion-only repair.
        return {
            "said": (still, motion),
            "constants": (),
            "picture": (still,) if layer == MOTION else (),
            "fields": {
                "still_prompt": (still,) if layer == STILL else (),
                "motion_prompt": (motion,),
            },
        }
    words = _layer_words(context, layer, package, visual)
    constants = [*words["still_fixed"], *words["motion_fixed"]]
    picture: list[str] = []
    if layer == MOTION:
        picture = [words["still"], *_flat(words["kept"].values())]
    else:
        constants += _flat(words["kept"].values())
    return {
        "said": (words["still"], words["motion"]),
        "constants": tuple(text for text in constants if text.strip()),
        "picture": tuple(text for text in picture if text.strip()),
        "fields": {name: tuple(said) for name, said in words["chosen"].items()},
    }


#: Said instead of the whole still under a motion rewrite's fixed sentences: the still is in
#: the prompts beside it already (2026-10-12 evening review: it was sent twice, and the
#: payloads ran 16-19 thousand characters).
STILL_KEPT_WHOLE = "every word of the still prompt stays as it is on this layer"


def layer_terms(
    context: dict[str, Any],
    layer: str,
    *,
    package: dict[str, Any] | None = None,
    visual: str | None = None,
) -> dict[str, Any]:
    """What the Video Editor may change on ``layer`` and the words he cannot, for the brief,
    his rewrite and her review — read from the prompts as stored, or from ``package`` and
    ``visual`` once rewritten.

    2026-10-12, 16:46-16:48, f06808c9 scenes 3, 4, 7: her review of a serial motion rewrite
    named «toward the subject», «ending close on it» (the camera move's own sentence) and
    «Sarah leans in a fraction», «turning fully toward her» (the beat's action, which the motion
    layer keeps word for word) as untreated; his second rewrite could change none of them and
    nothing turned to the picture. Returns {"layer", "fields_he_may_change" (field: what it
    becomes), "kept_word_for_word" (field: its words), "fixed_sentences" ({"still", "motion"}:
    the composer's sentences no field of his writes), "said_by_his_fields" (field: the
    sentences his choice of it says — the move's own sentence under ``camera_move``: his to
    change, never a lock), "camera_move": the move whose sentence the motion opens with}, and
    on a motion rewrite "still_kept_whole" (`STILL_KEPT_WHOLE`; the still is in the prompts
    beside it)."""
    active = package or context["package"]
    if active.get("prompt_format") == "editor_final_v1" or context.get("final_rewrite"):
        still = str(active.get("still_prompt") or context["visual_prompt"])
        editable = (
            {
                "still_prompt": "Write the exact final still text; no composer.",
                "motion_prompt": "Write the matching exact final clip text.",
                "camera_move": "Single enumerated camera move",
            }
            if layer == STILL
            else {
                "motion_prompt": "Write the exact final clip movement text.",
                "camera_move": "Single enumerated camera move",
            }
        )
        return {
            "layer": layer,
            "fields_he_may_change": editable,
            "kept_word_for_word": {"still_prompt": still} if layer == MOTION else {},
            "fixed_sentences": {"still": [], "motion": []},
            "said_by_his_fields": {},
            "camera_move": active.get("camera_move") or "",
            **({"still_kept_whole": STILL_KEPT_WHOLE} if layer == MOTION else {}),
        }
    words = _layer_words(context, layer, package, visual)
    terms: dict[str, Any] = {
        "layer": layer,
        "fields_he_may_change": words["fields"],
        "kept_word_for_word": words["kept"],
        "fixed_sentences": {"still": words["still_fixed"], "motion": words["motion_fixed"]},
        "said_by_his_fields": words["chosen"],
        "camera_move": words["package"].get("camera_move") or "",
    }
    if layer == MOTION:
        terms["still_kept_whole"] = STILL_KEPT_WHOLE
    return terms


def camera_move_sentences() -> dict[str, str]:
    """The fixed words each camera move is said in (`prompt_agent.MOVE_SENTENCES`)."""
    from app.media.prompt_agent import MOVE_SENTENCES  # noqa: PLC0415 - it imports us

    return dict(MOVE_SENTENCES)


def _data(context: dict[str, Any], **more: Any) -> dict[str, Any]:
    """The context as the agents read it, before the studio's lessons and the fitting
    (`_fitted`)."""
    from app.media.visual_policy import effective_policy  # noqa: PLC0415

    bible, _ = effective_policy(context["bible"], context["bible"])
    package, retired = effective_policy(context["package"], bible)
    scene_keys: tuple[str, ...] = (
        "scene_index",
        "story_purpose",
        "narration",
        "seconds",
        "writer_visual",
    )
    if context.get("serial"):
        # The beat's part, room, lines and background people: who speaks and where they stand.
        scene_keys += ("part", "location", "lines", "background")
    scene_view = {key: context["scene"].get(key) for key in scene_keys}
    intent = context.get("editorial_visual_intent") or package.get("editorial_visual_intent")
    if intent:
        scene_view["writer_visual"] = intent
    data = {
        "film": {"title": context["title"], "story": context["story"]},
        "scene": scene_view,
        "shot_as_stored": _shot_of(package),
        "prompts_sent": {
            "still": package.get("still_prompt") or context["visual_prompt"],
            "motion": package.get("motion_prompt") or "",
            "negative_prompt": package.get("negative_prompt"),
        },
        "visual_bible": {
            key: bible.get(key)
            for key in ("style", "world", "lighting", "continuity_rules", "avoid", "face_policy")
            if bible.get(key)
        },
        "current_policy": POLICY_NOTE,
        "editorial_visual_intent": context.get("editorial_visual_intent")
        or package.get("editorial_visual_intent"),
        "editorial_authority": context.get("editorial_authority")
        or package.get("editorial_authority"),
        "retired_restrictions": retired,
        "prompt_contract": "editor_final_v1"
        if context.get("final_rewrite")
        else package.get("prompt_format", "legacy"),
        "refusals": list(context["failures"]),
        "earlier_briefs": list(context["briefs"]),
        **more,
    }
    if context.get("older_briefs"):
        data["older_briefs_in_short"] = list(context["older_briefs"])
    if context.get("serial"):
        data["serial_shot"] = _serial_shot(context)
    if context.get("markings"):
        # The plan's objects that carry their own markings (`_markings_note`).
        data["planned_markings"] = list(context["markings"])
    return data


def _markings_note(context: dict[str, Any]) -> str:
    """Added to her brief and her review when the plan names an object that carries its own
    markings (`markings.planned_markings`; the Owner, 2026-10-13, the Kelvin film's thermometer
    refused for its digits): its scale is the object, not writing in the picture, and no
    rewrite is asked to take it away."""
    marked = tuple(context.get("markings") or ())
    if not marked:
        return ""
    return (
        markings_note(marked)
        + " A finding that reads such markings as text in the picture is a misreading, "
        "treated by nothing he writes: rate it minor, never brief him to remove the object's "
        "scale or to leave the object blank; only writing elsewhere is a defect of the "
        "words.\n"
    )


def _dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


#: The prose of the data that the instructions say again in their own words: dropped, after
#: the scene's history, when the payload is still over its budget (2026-10-12 evening review:
#: the layer's terms and the serial shot's prose could not shrink, and the payloads ran
#: 16-19 thousand characters).
_SERIAL_PROSE = ("how_the_still_is_composed", "how_the_clip_is_composed")


def _terms_said_short(fitted: dict[str, Any]) -> bool:
    """The layers' terms with the fields he may change named, not described (the instructions
    say what each becomes). True when something was shortened."""
    found = [fitted.get("this_layer"), *(fitted.get("layers_he_may_change") or {}).values()]
    changed = False
    for terms in found:
        if isinstance(terms, dict) and isinstance(terms.get("fields_he_may_change"), dict):
            terms["fields_he_may_change"] = list(terms["fields_he_may_change"])
            changed = True
    return changed


def _moves_said_short(fitted: dict[str, Any]) -> bool:
    """The camera moves named, not said (the instructions list them; the move he chose is
    said in this_layer's said_by_his_fields). True when something was shortened."""
    moves = fitted.get("camera_move_sentences")
    if isinstance(moves, dict) and moves:
        fitted["camera_move_sentences"] = sorted(moves)
        return True
    return False


def _refusals_said_short(fitted: dict[str, Any]) -> bool:
    """The refusals without the words quality_control_findings already gives by id. True
    when something was shortened."""
    if not fitted.get("quality_control_findings"):
        return False
    changed = False
    for refusal in fitted.get("refusals") or []:
        if isinstance(refusal, dict) and refusal.get("reasons"):
            refusal["reasons"] = []
            refusal["reasons_given_by_id"] = True
            changed = True
    return changed


def _fitted(data: dict[str, Any], lessons: list[str], limit: int = MAX_PAYLOAD_CHARS) -> str:
    """Keep current and historical evidence complete; the budget is advisory for batching."""
    from app.media.prompt_agent import fit_with_lessons  # noqa: PLC0415

    return _dumps(fit_with_lessons(data, lessons, limit))


# ------------------------------------------------------------------ her brief


def director_brief(
    engine: Engine, registry: Any, context: dict[str, Any], correlation_id: str
) -> dict[str, Any]:
    """The Director's brief for one scene (`SceneBrief`), asked through `structured_run`.

    Returns {"brief": dict | None, "run_id", "agent_id", "reason"}: no brief when no Director is
    active or her answer did not validate twice (the scene then waits, as before).

    She reads the studio's prompt lessons for the film's kind (`prompt_agent.prompt_lessons`,
    whole, before the film's data is fitted) and, in the scene's earlier briefs, the reviews of
    their rewrites — cause, why_not, lesson — so a diagnosis or a change that was refused or
    failed is not asked again (2026-10-12, f06808c9 scenes 3, 4, 7); quality control's
    findings with their ids, and for each open layer what the editor may change and the words
    that stay (`layer_terms`)."""
    from app.agents.structured import structured_run  # noqa: PLC0415 - it imports services
    from app.media.prompt_agent import lessons_rule, prompt_lessons  # noqa: PLC0415

    with Session(engine) as session:
        director = agent_for_role(session, "Director")
        director_id = director.id if director is not None else None
    if director_id is None or registry is None:
        return {"brief": None, "run_id": None, "agent_id": None, "reason": "Niciun Director activ."}
    with Session(engine) as session:
        lessons = prompt_lessons(session, scope=lesson_scope(context))
    context = {**context, "final_rewrite": True}
    layers = tuple(context["layers"])
    failures = context["failures"]
    more: dict[str, Any] = {
        "open_layers": list(layers),
        "layers_he_may_change": {layer: layer_terms(context, layer) for layer in layers},
        "camera_move_sentences": ({} if context.get("final_rewrite") else camera_move_sentences()),
    }
    findings = review_findings(context)
    if findings:
        more["quality_control_findings"] = findings
    delivery = context.get("delivery_failure")
    prompt = (
        _BRIEF_INSTRUCTIONS.format(
            scene=context["scene_index"],
            title=context["title"],
            failures=f"{len(failures)} refusal(s)" if failures else "refused",
            layers=str(context.get("layers_note") or _LAYERS_OPEN.get(layers, "")),
            action="retry_delivery" if delivery else "rewrite",
        )
        + (_SERIAL_BRIEF_NOTE if context.get("serial") else "")
        + POLICY_NOTE
        + _markings_note(context)
        + lessons_rule(lessons)
        + wrap_in_inert_boundary(_fitted(_data(context, **more), lessons), "scene-brief")
    )
    if delivery:
        prompt += (
            "\nThis is a terminal PROVIDER DELIVERY failure, not a visual rejection: no "
            "picture or clip was delivered for the failed take. Do not invent a visual "
            "defect and do not change the scene's approved prompts to treat a delivery "
            "error. Return action: retry_delivery, with the open layer, a diagnosis of "
            "the delivery failure, avoid duplicate/in-flight requests, keep the approved "
            "prompts and takes, and change the delivery attempt. The studio verifies the "
            "terminal journal and normal paid-attempt/budget/approval/STOP gates before "
            "retrying; your decision alone buys nothing.\n"
            + wrap_in_inert_boundary(_dumps(delivery), "delivery-failure")
        )
    parsed, first, second = structured_run(
        engine,
        registry,
        director_id,
        BRIEF_TASK,
        prompt,
        BRIEF_TEMPLATE,
        correlation_id,
        brief_schema(layers, delivery=bool(delivery)),
        "",
        summary=(
            f"Preiau livrarea scenei {context['scene_index']} din «{context['title']}»."
            if delivery
            else f"Citesc promptul scenei {context['scene_index']} din «{context['title']}» "
            "și motivele controlului; îi scriu lui Kael ce să evite."
        ),
        max_tokens=2500,
        subject={
            "storyboard_id": context.get("storyboard_id"),
            "scene_index": context.get("scene_index"),
        },
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


def _direct_rewritten_package(
    context: dict[str, Any], new: dict[str, Any], layer: str
) -> dict[str, Any]:
    """No compositor: preserve the untouched layer and Kael's exact corrected prose."""
    from app.media.final_prompts import FinalPromptError, editor_compiled  # noqa: PLC0415
    from app.media.visual_policy import effective_policy, orientation_conflict  # noqa: PLC0415

    stored = context["package"]
    package, retired = effective_policy(stored, context.get("bible") or {})
    _, retired_bible = effective_policy(context.get("bible") or {}, context.get("bible") or {})
    intent = context.get("editorial_visual_intent") or stored.get("editorial_visual_intent")
    if orientation_conflict(stored, context.get("bible") or {}) and not intent:
        raise FinalPromptError(
            "PLAN_CONFLICT: medalii pe piept din spate; Sarah trebuie sa aprobe "
            "editorial_visual_intent coerent inainte de rescriere."
        )
    if intent:
        package["editorial_visual_intent"] = intent
        package["writer_visual"] = intent
        if context.get("editorial_authority"):
            package["editorial_authority"] = context["editorial_authority"]
    migrating = stored.get("prompt_format") != "editor_final_v1"
    if migrating:
        if not new.get("still_prompt") or not new.get("motion_prompt"):
            raise FinalPromptError(
                "Migrarea cere still_prompt si motion_prompt complete de la Kael."
            )
        historical_still = stored.get("still_prompt") or context.get("visual_prompt")
        if layer == MOTION and new["still_prompt"] != historical_still:
            raise FinalPromptError("Migrarea motion trebuie sa pastreze still_prompt exact.")
        if layer == MOTION:
            package["still_prompt"] = historical_still
        package["legacy_migration"] = {
            "from_format": "legacy",
            "retired_restrictions": retired
            + [{**item, "field": "bible." + item["field"]} for item in retired_bible],
            "preserved_still": layer == MOTION,
        }
    if layer == STILL:
        package["still_prompt"] = new["still_prompt"]
        package["motion_prompt"] = new["motion_prompt"]
        # Planning notes are metadata; only Kael's final prompt is sent.
        for name in SHOT_FIELDS:
            if name not in ("avoid", "second_framing") and new.get(name) not in ("", None, [], {}):
                package[name] = new[name]
    else:
        # A motion correction NEVER touches the paid/approved still identity.
        package["motion_prompt"] = new["motion_prompt"]
        if new.get("camera_move") in lint.CAMERA_MOVES:
            package["camera_move"] = new["camera_move"]
        if new.get("ending_frame"):
            package["ending_frame"] = new["ending_frame"]
    # An omitted/empty negative clears a previous exclusion; never resurrect old bans.
    package["negative_prompt"] = new.get("negative_prompt") or None
    package["prompt_format"] = "editor_final_v1"
    package["source"] = "model"
    package.update(editor_compiled(package))
    return package


def rewritten_package(
    context: dict[str, Any], shot: BaseModel, layer: str, brief: dict[str, Any]
) -> dict[str, Any]:
    """A requested LIVE rewrite always returns validated Kael-owned final text."""
    return _direct_rewritten_package(context, shot.model_dump(), layer)


def serial_rewritten_package(
    context: dict[str, Any], shot: BaseModel, layer: str, brief: dict[str, Any]
) -> dict[str, Any]:
    """Serial rewrites use the same exact-text contract, preserving the series look."""
    return _direct_rewritten_package(context, shot.model_dump(), layer)


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


def _pieces(reason: Any) -> list[str]:
    """One refusal's words as its findings: the still gate and clip QC join their reasons with
    «; », and a quote («…») or an aside ((…)) may hold a semicolon of its own (2026-10-12
    evening review: «prag 15%)» was split off its sentence)."""
    text = _norm(reason)
    pieces: list[str] = []
    depth, start = 0, 0
    for position, char in enumerate(text):
        if char in "«(":
            depth += 1
        elif char in "»)":
            depth = max(0, depth - 1)
        elif char == ";" and depth == 0:
            pieces.append(text[start:position])
            start = position + 1
    pieces.append(text[start:])
    return [piece.strip(" ;") for piece in pieces if piece.strip(" ;")]


def _is_finding(text: str) -> bool:
    """Whether ``text`` says something about the picture: not the gate's verdict line, not one
    of the studio's own process notes (`fix_check.PROCESS_NOTES`: «Scena 7: mișcarea filmată
    din imaginea nouă.» rode as the film's finding on every brief of f06808c9 scene 7; and
    `_PROCESS_NOTES`), not her second look's words before a purchase (`_CONTEXT_PREFIXES`)."""
    from app.media import fix_check  # noqa: PLC0415 - it imports us

    said = _norm(text).casefold()
    if any(said.startswith(prefix) for prefix in (*_NOT_A_FINDING, *_CONTEXT_PREFIXES)):
        return False
    notes = (*getattr(fix_check, "PROCESS_NOTES", ()), *_PROCESS_NOTES)
    return not any(pattern.search(_norm(text)) for pattern in notes)


def hard_limit(text: Any, bible: dict[str, Any] | None, markings: Sequence[str] = ()) -> bool:
    """Whether quality control's words name what the bible's hard limits forbid
    (`HARD_LIMIT_WORDS`; a face, when the bible forbids faces): such a finding is serious
    whatever a review says (2026-10-12 evening review of a50407e). Writing alone is not one
    when the plan names an object that carries its own markings (``markings``,
    `markings.planned_markings`): a thermometer's scale is the object, and her review rates
    the finding (the Owner, 2026-10-13)."""
    said = _norm(text)
    if _OTHER_LIMITS.search(said):
        return True
    if _WRITING_LIMIT.search(said):
        return not markings
    return bool(lint.bible_face_rule(bible or {})) and bool(_FACE_WORDS.search(said))


def review_findings(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Quality control's findings this rewrite must treat, each with an id her review answers
    by (2026-10-12, f06808c9 scene 7: her review listed her own diagnoses as findings and
    missed that quality control's one finding was treated): the finished film's (from
    `rewrite_for_redo`, each with the cause the Director found for it when there is one) and,
    when the scene's newest take is quality control's refusal, that refusal, one finding per
    reason. Older refusals are history for the brief, not findings for this rewrite: a panels
    refusal answered weeks ago would make every later rewrite MISS. Each item is {"id",
    "qc_text", "source" (the refused take's kind, or "film"), "code"} and its "cause"."""
    failures = list(context.get("failures") or [])
    current = [item for item in failures if item.get("kind") == "film"]
    if context.get("last_code") in QUALITY_CODES:
        newest = next((item for item in failures if item.get("kind") != "film"), None)
        if newest is not None:
            current.append(newest)
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for failure in current or failures[:1]:
        causes = list(failure.get("causes") or [])
        for position, reason in enumerate(failure.get("reasons") or []):
            cause = _norm(causes[position] if position < len(causes) else "")
            cause = cause or _norm(failure.get("cause"))
            # A take's refusal was split into its findings whole, before any cut
            # (`refusal_findings`); the film's findings come one by one, each whole.
            for piece in [_norm(reason)]:
                if not piece or not _is_finding(piece) or piece.casefold() in seen:
                    continue
                seen.add(piece.casefold())
                item = {
                    "id": len(found) + 1,
                    "qc_text": piece,
                    "source": failure.get("kind"),
                    "code": failure.get("code"),
                }
                if cause:
                    item["cause"] = cause
                found.append(item)
    return found


#: A brief the Director wrote in her audit of the words before a purchase
#: (`prompt_audit._brief_of`): the rewrite treats her diagnosis, not quality control's past.
AUDIT_BRIEF = "prompt_audit"


def findings_to_treat(context: dict[str, Any], brief: dict[str, Any]) -> list[dict[str, Any]]:
    """The findings her review answers: quality control's (`review_findings`) or, when it named
    nothing a picture could show (only the studio's own notes), her brief's diagnosis, which is
    then what the rewrite was asked to treat.

    A brief from her audit of the words (``source`` AUDIT_BRIEF) is answered by its diagnosis
    alone: no picture was refused — the words were — and a refusal in the scene's history is
    another candidate's (2026-10-15, 7c26a7ce scene 1: the motion rewrite her audit asked was
    reviewed against the still gate's findings on the candidate it had refused, beside the one
    it approved — «a bright window with daylight» — and refused as «locked to the picture»)."""
    found = [] if brief.get("source") == AUDIT_BRIEF else review_findings(context)
    if found:
        return found
    return [
        {
            "id": 1,
            "qc_text": _cut(brief.get("diagnosis"), 400),
            "source": "director_brief",
            "code": None,
        }
    ]


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
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The Director's review of the rewritten prompts against quality control's findings
    (`RewriteReview`, bound by `review_schema`), asked through `structured_run` before anything
    is stored or bought.

    Returns {"verdict": TREATS | MISSES | ACCEPTED_MINOR | None, "reason_ro", "findings" (the
    record's items, `_kept_findings`), "observations", "broken_lessons" (each with the
    studio's ``confirmed``), "blocking" (ids of the serious untreated findings), "locked_only"
    (every reason it refuses is words this layer keeps), "lock" (where: `LOCK_PICTURE` or
    `LOCK_COMPOSER`), "locked_words", "minor" (the ids rated minor), "cause", "lesson",
    "run_id", "reason"}: no verdict when no Director is active or her answer did not validate
    twice, and the caller fails closed — nothing is bought on words nobody verified (Owner,
    2026-10-12: «tratează problema? Promptul trebuie revizuit»). ``earlier`` is her review of
    his first rewrite in the rung, when this is his second: she checks the findings it left
    untreated first, and a finding it found serious stays serious. ``findings`` are the ones to
    answer (`findings_to_treat`, computed once per rung); one that names a hard limit of the
    bible is serious whatever she says (`hard_limit`)."""
    from app.agents.structured import structured_run  # noqa: PLC0415 - it imports services
    from app.media.prompt_agent import (  # noqa: PLC0415
        STILL_FRAMING_RULE,
        lessons_rule,
        prompt_lessons,
    )

    with Session(engine) as session:
        director = agent_for_role(session, "Director")
        director_id = director.id if director is not None else None
    if director_id is None or registry is None:
        return _no_review(None, "niciun Director activ care să verifice rescrierea")
    with Session(engine) as session:
        lessons = prompt_lessons(session, scope=lesson_scope(context))
    qc = findings if findings is not None else findings_to_treat(context, brief)
    stored = context["package"]
    old_still = str(stored.get("still_prompt") or context["visual_prompt"])
    old_motion = str(stored.get("motion_prompt") or "")
    new_motion = str(package.get("motion_prompt") or "")
    from app.media.visual_policy import effective_policy  # noqa: PLC0415

    terms = layer_terms(context, layer, package=package, visual=visual)
    data: dict[str, Any] = {
        "quality_control_findings": qc,
        "director_brief": {
            key: brief.get(key)
            for key in ("layer", "diagnosis", "avoid", "change", "keep", "editorial_visual_intent")
        },
        "this_layer": terms,
        "camera_move_sentences": {}
        if package.get("prompt_format") == "editor_final_v1"
        else camera_move_sentences(),
        "visual_bible": effective_policy(context["bible"], context["bible"])[0],
        "current_policy": POLICY_NOTE,
        "prompt_contract": package.get("prompt_format", "legacy"),
        "editorial_visual_intent": context.get("editorial_visual_intent")
        or package.get("editorial_visual_intent"),
        "editorial_authority": context.get("editorial_authority")
        or package.get("editorial_authority"),
        "prompts_before": {"still": old_still, "motion": old_motion},
        "prompts_after": {"still": visual, "motion": new_motion},
        "negative_prompt_before": stored.get("negative_prompt"),
        "negative_prompt_after": package.get("negative_prompt"),
        "difference": {
            "still": sentence_diff(old_still, visual),
            "motion": sentence_diff(old_motion, new_motion),
        },
    }
    if context.get("serial"):
        data["serial_shot"] = _serial_shot(context)
    if context.get("markings"):
        # The plan's objects that carry their own markings (`_markings_note`).
        data["planned_markings"] = list(context["markings"])
    if earlier:
        data["your_earlier_review"] = {
            "verdict": earlier.get("verdict"),
            "findings": _earlier_findings(earlier.get("findings")),
            "broken_lessons": earlier.get("broken_lessons") or [],
            "cause": earlier.get("cause") or "",
        }
    prompt = (
        _REVIEW_INSTRUCTIONS.format(
            scene=context["scene_index"],
            title=context["title"],
            layer=layer,
            lesson_chars=LESSON_CHARS_ASKED,
        )
        + (_SECOND_REVIEW_NOTE if earlier else "")
        + POLICY_NOTE
        + (
            " EDITOR_FINAL: every candidate sentence is Kael's final text. No fixed "
            "compositor sentence exists; only the paid still stays locked on motion. "
            "Evaluate the approved editorial_visual_intent over the old plan's orientation. "
            "For refusal name the exact defect, quote, change, keep and whether its source "
            "is Kael, plan, editorial policy or code.\n"
            if package.get("prompt_format") == "editor_final_v1"
            else ""
        )
        + _markings_note(context)
        + lessons_rule(lessons)
        + (_REVIEW_LESSONS_NOTE if lessons else "")
        + (STILL_FRAMING_RULE if layer == STILL else "")
        + wrap_in_inert_boundary(_fitted(data, lessons), "rewrite-review")
    )
    editable = tuple(terms["fields_he_may_change"])
    # Serious whatever she says: the bible's hard limits, and what her earlier review in this
    # rung found serious (2026-10-12 evening review of a50407e). Writing on an object the plan
    # asks for with its own markings is not one (2026-10-13).
    serious = {
        int(item["id"])
        for item in qc
        if hard_limit(item.get("qc_text"), context["bible"], context.get("markings") or ())
    }
    serious |= {
        int(item.get("id") or 0)
        for item in (earlier or {}).get("findings") or []
        if isinstance(item, dict) and item.get("severity") == SERIOUS
    }
    parsed, first, second = structured_run(
        engine,
        registry,
        director_id,
        REVIEW_TASK,
        prompt,
        REVIEW_TEMPLATE,
        correlation_id,
        review_schema(
            tuple(int(item["id"]) for item in qc),
            editable,
            lock_texts(context, layer, package=package, visual=visual),
            serious=serious,
            lessons=lessons,
        ),
        "",
        summary=(
            f"Verific dacă rescrierea scenei {context['scene_index']} din "
            f"«{context['title']}» tratează constatările înainte să cumpărăm ceva pe ea."
        ),
        max_tokens=2400,
        subject={
            "storyboard_id": context.get("storyboard_id"),
            "scene_index": context.get("scene_index"),
        },
    )
    last = second or first
    if parsed is None:
        return _no_review(
            last.get("id"),
            "verificarea rescrierii nu a respectat forma cerută nici a doua oară "
            f"({last.get('error_detail') or last.get('status')})",
        )
    blocking = parsed.blocking
    # Every reason the rewrite is refused for is words this layer keeps: no rewrite on it can
    # treat them (2026-10-12, f06808c9 scenes 3, 4, 7). Where they live decides what comes
    # next: the picture's words turn a motion rewrite to the picture; the composer's own
    # sentences alone are a tool's defect no rewrite treats (the evening review of a50407e).
    locked_only = (
        bool(blocking)
        and not parsed.refusing_lessons
        and all(item.locked and item.lock_kind for item in blocking)
    )
    lock = None
    if locked_only:
        lock = (
            LOCK_PICTURE
            if any(item.lock_kind == LOCK_PICTURE for item in blocking)
            else LOCK_COMPOSER
        )
    return {
        "verdict": parsed.verdict,
        "reason_ro": parsed.reason_ro,
        "findings": _kept_findings([item.model_dump() for item in parsed.findings], qc, layer),
        "observations": list(parsed.observations),
        "broken_lessons": [item.model_dump() for item in parsed.broken_lessons],
        "blocking": [item.id for item in blocking],
        "locked_only": locked_only,
        "lock": lock,
        "locked_words": [item.locked_words for item in blocking if item.locked],
        # Every finding minor (`ACCEPTED_MINOR`): their ids, for the caller that accepts the take.
        "minor": [item.id for item in parsed.findings if item.severity == MINOR],
        "cause": parsed.cause,
        "lesson": parsed.lesson,
        "run_id": last.get("id"),
        "reason": "",
    }


#: What her second review is shown of her first, per finding: quality control's words are in
#: quality_control_findings by the same id (2026-10-12 evening review: the earlier review
#: repeated them and ran 5 thousand characters on its own).
_EARLIER_FINDING_KEYS = ("id", "treated", "severity", "by", "why_not", "field", "locked")


def _earlier_findings(findings: Any) -> list[dict[str, Any]]:
    return [
        {key: item[key] for key in _EARLIER_FINDING_KEYS if item.get(key) not in (None, "")}
        for item in findings or []
        if isinstance(item, dict)
    ]


def _no_review(run_id: str | None, reason: str) -> dict[str, Any]:
    """A review that could not be made: no verdict, and the reason; the caller fails closed."""
    return {
        "verdict": None,
        "reason_ro": "",
        "findings": [],
        "observations": [],
        "broken_lessons": [],
        "blocking": [],
        "locked_only": False,
        "lock": None,
        "locked_words": [],
        "minor": [],
        "cause": "",
        "lesson": "",
        "run_id": run_id,
        "reason": reason,
    }


# ------------------------------------------------------------------ what a review teaches


def learn_from_review(
    session: Session, review: dict[str, Any], context: dict[str, Any]
) -> tuple[bool, str]:
    """The lesson of a review that passed a rewrite, kept for every future prompt of the film's
    kind (`prompt_agent.record_prompt_lesson`, read by the shot writer, the rewrites and every
    brief) — unverified: words passed on their own prove nothing until the picture bought on
    them shows the finding gone (the stills gate confirms it under the review's run, or
    withdraws it when the finding persists). The store decides what is a rule (no film, scene
    or id named) and folds a lesson it already has into the newer one. Returns (recorded, why
    not). Inside the caller's write transaction. Owner, 2026-10-12: «DIRECTOAREA ACCEPTĂ
    DEFECTELE MICI! DAR TREBUIE SĂ ÎNȚELEAGĂ DE CE APAR DEFECTELE ȘI LA VIITOARELE PROMPTURI SĂ
    SE ASIGURE CĂ NU MAI SUNT!»"""
    from app.media.prompt_agent import record_prompt_lesson  # noqa: PLC0415 - it imports us

    lesson = " ".join(str(review.get("lesson") or "").split())
    if not lesson:
        return False, "recenzia nu a tras nicio regulă generală din acest defect"
    recorded = record_prompt_lesson(
        session,
        lesson,
        source_id=review.get("run_id"),
        scope=lesson_scope(context),
        provisional=True,
    )
    if not recorded:
        return False, (
            "lecția nu a fost păstrată: nu e o regulă pentru orice prompt (numește un film, o "
            "scenă sau un id) sau e prea lungă"
        )
    return True, ""


def _lint_blocks(
    context: dict[str, Any], package: dict[str, Any], visual: str, *, layer: str | None = None
) -> list[str]:
    """The linter's BLOCK findings this scene's new prompts would add (none it had before)."""

    def blocks(still: str, motion: str) -> set[str]:
        found = lint.lint_scene(
            lint.LintScene(
                scene=int(context["scene_index"]),
                kind="LIVE",
                still_prompt=still,
                motion_prompt=motion,
                contract={
                    "prompt_max_chars": {
                        "text_to_image": context["look"]["max_prompt_chars"],
                        "image_to_video": lint.DEFAULT_PROMPT_MAX_UTF16,
                    }
                }
                if context.get("serial") and context.get("look") and not context.get("contract")
                else context.get("contract"),
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
    from app.media.prompt_agent import composition_issues  # noqa: PLC0415

    if package.get("prompt_format") != "editor_final_v1":
        after.update(
            composition_issues(
                package,
                visual,
                str(package.get("motion_prompt") or ""),
                layers=(MOTION,) if layer == MOTION else (STILL, MOTION),
            )
        )
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
                + "; ".join(refused)
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
            shot_schema(
                index,
                layer,
                serial=serial,
                editor_final=True,
                migrating=context["package"].get("prompt_format") != "editor_final_v1",
            ),
            "",
            summary=(f"Rescriu scena {index} din «{context['title']}» după brief-ul Directoarei."),
            max_tokens=3000,
            temperature=0.3,
            subject={"storyboard_id": context.get("storyboard_id"), "scene_index": index},
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
        try:
            candidate = rewrite(context, parsed, layer, brief)
        except ValueError as exc:
            refused = [f"Prompt final invalid: {exc}"]
            continue
        candidate_visual = (
            visual if layer == MOTION else str(candidate.get("still_prompt") or visual)
        )
        refused = _lint_blocks(context, candidate, candidate_visual, layer=layer)
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
        "reason": "Verificarea promptului a blocat rescrierea: " + "; ".join(refused),
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
    findings: list[dict[str, Any]],
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
            findings=findings,
        )
    except Exception as exc:  # noqa: BLE001 - a fault waits; it never buys
        logger.warning("rewrite_review_failed", extra={"error": type(exc).__name__})
        return _no_review(
            None, f"verificarea rescrierii nu a putut fi făcută ({type(exc).__name__})"
        )


def _kept_findings(findings: Any, qc: list[dict[str, Any]], layer: str) -> list[dict[str, Any]]:
    """Her review's findings as the record keeps them. CONTRACT (2026-10-12): each item is
    {"id", "qc_text" (quality control's own words for it), "finding" (her few words, else
    quality control's), "treated", "by" (the new sentence that treats it), "why_not",
    "severity" (minor | serious), "layer" (still | motion: the prompt the defect lives in;
    the rewrite's layer when she did not say), "accepted" (an untreated MINOR finding: she
    accepts it, so it is never open, never blocking and never withdraws a lesson — the
    contract of 2026-10-12 evening; FC builds must_fix only from treated items and untreated
    serious ones)}, with "field" (the field she named), "locked" (the words that invite it are
    ones the rewrite's layer keeps), "lock" (where those words live: `LOCK_PICTURE` or
    `LOCK_COMPOSER`) and "source" (the refused take's kind, "film", or "director_brief" when
    quality control named nothing a picture could show and her diagnosis stood in,
    `findings_to_treat`) beside them — what the stills gate checks the picture bought on the
    words against (`fix_check`)."""
    given = {int(item["id"]): item for item in qc}
    kept: list[dict[str, Any]] = []
    for item in findings or []:
        if not isinstance(item, dict):
            continue
        number = int(item.get("id") or 0)
        qc_text = str(given.get(number, {}).get("qc_text") or "")
        treated = bool(item.get("treated"))
        severity = str(item.get("severity") or SERIOUS)
        kept.append(
            {
                "id": number,
                "qc_text": qc_text,
                "finding": str(item.get("finding") or "") or qc_text,
                "treated": treated,
                "by": str(item.get("by") or ""),
                "why_not": str(item.get("why_not") or ""),
                "severity": severity,
                "layer": str(item.get("layer") or layer),
                "accepted": not treated and severity == MINOR,
                "field": str(item.get("field") or ""),
                "locked": bool(item.get("locked")),
                "lock": str(item.get("lock_kind") or ""),
                "source": given.get(number, {}).get("source"),
            }
        )
    return kept


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
        "findings": list(review.get("findings") or []),
        "observations": list(review.get("observations") or []),
        "broken_lessons": list(review.get("broken_lessons") or []),
        "locked_only": bool(review.get("locked_only")),
        "lock": review.get("lock"),
        "still_prompt": str(written.get("visual") or ""),
        "motion_prompt": str(package.get("motion_prompt") or ""),
    }


def _unchanged_still_record(number: int, written: dict[str, Any]) -> dict[str, Any]:
    """A round of a still brief whose rewrite left the picture's words as they were: no review
    is asked on the motion's terms (2026-10-12 evening review of a50407e); the round is kept,
    refused, with why, and his second rewrite is told so (`_STILL_UNCHANGED_NOTE`)."""
    package = written["package"] or {}
    return {
        "round": number,
        "layer": STILL,
        "rewrite_run_id": written.get("run_id"),
        "review_run_id": None,
        "verdict": None,
        "still_unchanged": True,
        "reason_ro": "",
        "reason": "the picture's words did not change",
        "cause": "",
        "lesson": "",
        "findings": [],
        "observations": [],
        "broken_lessons": [],
        "locked_only": False,
        "lock": None,
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
    """Her review of his refused rewrite, for his second: each untreated finding with why and
    the field she named (a locked one marked as not his on this layer), the lessons his words
    break (an unverified one marked advisory), the cause, the findings he did treat with their
    sentence, and his refused prompts — inside a boundary of its own, since the findings
    quote quality control's words. What he may change on the layer is in the rewrite's own
    data once (2026-10-12 evening review: it was sent twice, with the move table, and the
    payload ran past its budget). A round whose still brief left the picture's words as they
    were is told that (`_STILL_UNCHANGED_NOTE`)."""
    refused = {"still": record["still_prompt"], "motion": record["motion_prompt"]}
    if record.get("still_unchanged"):
        return _STILL_UNCHANGED_NOTE + wrap_in_inert_boundary(
            _dumps({"refused_prompts": refused}), "rewrite-feedback"
        )
    untreated = []
    for item in record["findings"]:
        if item["treated"] or item.get("accepted"):
            continue
        said = item.get("qc_text") or item.get("finding")
        entry = {"id": item.get("id")}
        if item.get("finding") and item.get("finding") != said:
            entry["finding"] = item.get("finding")
        entry.update(quality_control=said, why_not=item["why_not"], severity=item.get("severity"))
        if item.get("locked"):
            entry["locked"] = "words this layer keeps: not yours to change here"
        else:
            entry["field"] = item.get("field")
        untreated.append(entry)
    # Quality control's words for a treated finding are in the rewrite's data by the same id.
    treated = [
        {"id": item.get("id"), "by": item["by"]} for item in record["findings"] if item["treated"]
    ]
    broken = [
        {
            **{key: item.get(key) for key in ("lesson", "why_not", "field")},
            "advisory": not item.get("confirmed"),
        }
        for item in record.get("broken_lessons") or []
        if isinstance(item, dict)
    ]
    data = {
        "verdict": record["verdict"],
        "reason_ro": record["reason_ro"],
        "untreated": untreated,
        "broken_lessons": broken,
        "treated": treated,
        "cause": record["cause"],
        "refused_prompts": refused,
    }
    return _SECOND_REWRITE_NOTE + wrap_in_inert_boundary(_dumps(data), "rewrite-feedback")


#: Said when the motion layer cannot treat what quality control refused: the picture's turn.
_LAYER_EXHAUSTED_RO = (
    " Mișcarea nu poate trata constatarea: cuvintele care o cer sunt ale imaginii sau fixe pe "
    "stratul mișcării; e rândul imaginii."
)
#: Said instead when the picture is the Owner's (2026-10-12 evening review of a50407e).
_OWNER_STILL_RO = (
    " Mișcarea nu poate trata constatarea, iar imaginea e aprobată de Proprietar și nu se "
    "rescrie: nu se cumpără nimic, defectul e notat pentru dezvoltator și preluarea merge la "
    "privirea a doua a Directoarei."
)


def _second_rewrite_failed(
    outcome: dict[str, Any], why: str, *, exhausted: bool = False
) -> dict[str, Any]:
    """His second rewrite came to nothing her review could read (his answer, the linter, the
    old words or the refused ones again, a review of it nobody could make): her refusal of the
    first stands — its verdict, cause and reason — and nothing is stored or bought.
    ``exhausted``: the motion layer gave its stored or refused words again, so it has nothing
    else to say (`layer_exhausted`, the picture's turn; 2026-10-12, f06808c9 scenes 3, 4, 7)."""
    outcome["not_treating"] = True
    outcome["reason"] = (
        "Rescrierea nu tratează constatarea: "
        + str(outcome.get("review_reason_ro") or "")
        + f" A doua rescriere, cu observațiile ei: {why}"
        + (_LAYER_EXHAUSTED_RO if exhausted else "")
    )
    if exhausted:
        outcome["layer_exhausted"] = True
    return outcome


def _locked_on_layer(outcome: dict[str, Any], review: dict[str, Any], layer: str) -> dict:
    """Her review refused the rewrite only for words the layer keeps: another rewrite on it
    cannot treat them, so he is not asked again. Where the words live decides what comes next
    (`review_rewrite`'s ``lock``): in the picture's words on a motion rewrite it is the
    picture's turn (``layer_exhausted``: `rewrite_failed_scene` and `runbook.stages` turn to the
    still); only in the composer's own sentences — on any layer — no rewrite can treat them:
    ``composer_locked``, nothing is bought, the scene's developer is told once
    (`note_for_developer`) and the take goes to her second look (``second_look``), which
    accepts it or decides (2026-10-12 evening review of a50407e: her lock alone escalated and
    bought a new still)."""
    outcome["not_treating"] = True
    outcome["locked_findings"] = list(review.get("blocking") or [])
    outcome["locked_words"] = list(review.get("locked_words") or [])
    outcome["reason"] = "Rescrierea nu tratează constatarea: " + str(review.get("reason_ro") or "")
    if layer == MOTION and review.get("lock") == LOCK_PICTURE:
        outcome["layer_exhausted"] = True
        outcome["reason"] += _LAYER_EXHAUSTED_RO
        return outcome
    outcome["composer_locked"] = True
    outcome["second_look"] = True
    outcome["reason"] += (
        " Cuvintele care o cer sunt propozițiile fixe ale compozitorului de prompturi; nicio "
        "rescriere nu le poate schimba, așa că nu se cumpără nimic: defectul e notat pentru "
        "dezvoltator, iar preluarea merge la privirea a doua a Directoarei."
    )
    return outcome


def _accepted_minor(outcome: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    """Her review rated every one of quality control's findings minor (`ACCEPTED_MINOR`): the
    take is acceptable as it is, so the rewrite is not stored, nothing is bought on it and no
    lesson is drawn from a review that treated nothing; the caller hands the take to her
    second look or approves it (``accepted_minor``, ``accepted_minor_ids``). 2026-10-12 evening
    review of a50407e: a rewrite that treated nothing was stored and bought because each
    finding was minor. The Owner: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI!»"""
    outcome["accepted_minor"] = True
    outcome["accepted_minor_ids"] = list(review.get("minor") or [])
    outcome["second_look"] = True
    outcome["reason"] = (
        "Directoarea a cântărit constatările controlului: toate sunt defecte mici, pe care le "
        "acceptă. Rescrierea nu se păstrează și nu se cumpără nimic; preluarea merge la "
        "privirea ei a doua. " + str(review.get("reason_ro") or "")
    ).strip()
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
    "review_cause", "review_lesson", "review_attempts", "qc_findings", "old_still_prompt",
    "still_prompt", "old_motion_prompt", "motion_prompt"}; ``same_prompt`` True when his words
    came back the same, ``not_treating`` True when her review said MISSES, ``review_unavailable``
    True when nobody could review it — nothing is stored in the last two cases either —
    ``layer_exhausted`` True when the motion layer cannot treat the findings: every finding
    that refuses the rewrite is in the picture's words the motion layer keeps (`lock_texts`),
    or his second rewrite gave the stored or the refused words again. The caller turns to the
    picture then, as on ``same_prompt`` (`rewrite_failed_scene`, `runbook.stages`).
    ``composer_locked`` True (with ``second_look``) when they are only in the composer's own
    sentences: nothing is stored or bought, nobody escalates (`_locked_on_layer`).
    ``accepted_minor`` True (with ``accepted_minor_ids`` and ``second_look``) when every finding
    is minor: nothing is stored or bought (`_accepted_minor`).

    A rewrite her review refused is rewritten once more in the same rung, with her words: each
    untreated finding, why it is not treated and the field to change (2026-10-12, f06808c9
    scenes 3, 4, 7: the refused rewrites ended the rung and the next one asked the same brief)
    — unless every reason is locked on the layer, when another rewrite on it cannot help. A
    still brief whose rewrite left the picture's words as they were is not reviewed on the
    motion's terms: he is asked again, told so. Only a second miss stores nothing. A rewrite
    she passes stores the scene and her lesson, unverified (`learn_from_review`)."""
    from app.media.prompt_agent import (  # noqa: PLC0415 - it imports us
        PROMPT_ROLE,
        STILL_FRAMING_RULE,
        lessons_rule,
        prompt_lessons,
    )

    index = int(context["scene_index"])
    layer = str(brief["layer"])
    outcome: dict[str, Any] = {"rewritten": False, "layer": layer, "reason": "", "run_id": None}
    context = {**context, "final_rewrite": True}
    if brief.get("editorial_visual_intent"):
        if layer != STILL:
            outcome["reason"] = "PLAN_CONFLICT: schimbarea orientarii necesita rescriere still."
            return outcome
        context["editorial_visual_intent"] = brief["editorial_visual_intent"]
    with Session(engine) as session:
        editor = agent_for_role(session, PROMPT_ROLE)
        editor_id = editor.id if editor is not None else None
    if editor_id is None or registry is None:
        outcome["reason"] = "Niciun Video Editor activ."
        return outcome
    with Session(engine) as session:
        lessons = prompt_lessons(session, scope=lesson_scope(context))
    qc = findings_to_treat(context, brief)
    outcome["qc_findings"] = qc
    migrating = context["package"].get("prompt_format") != "editor_final_v1"
    response = {"scene_index": index, "camera_move": "...", "motion_prompt": "..."}
    if layer == STILL or migrating:
        response["still_prompt"] = "..."
    layer_rule = (
        "Write complete still_prompt and matching motion_prompt."
        if layer == STILL
        else (
            "Write complete motion_prompt and echo the existing still_prompt byte-for-byte "
            "to migrate this legacy package. The purchased still must stay exactly the same."
            if migrating
            else "Write complete motion_prompt only; keep the purchased still exactly."
        )
    )
    instructions = (
        _REWRITE_INSTRUCTIONS.format(
            scene=index,
            title=context["title"],
            layer=layer_rule,
            response=json.dumps(response, ensure_ascii=False),
            # The whole vocabulary («Mișcare v2», 2026-10-12): the old ten slow moves alone sent
            # every redo back to a slow move.
            moves=", ".join(lint.CAMERA_MOVES),
        )
        + lessons_rule(lessons)
        + POLICY_NOTE
        + (STILL_FRAMING_RULE if layer == STILL else "")
    )
    data = _data(
        context,
        director_brief=brief,
        quality_control_findings=qc,
        this_layer=layer_terms(context, layer),
        camera_move_sentences={},
        provider_limits={
            "still_utf16": lint.prompt_cap(context.get("contract"), "still"),
            "motion_utf16": lint.prompt_cap(context.get("contract"), "motion"),
        },
    )

    def asked(note: str) -> str:
        # The scene's data and her review of his refused words are fitted TOGETHER to the
        # budget (2026-10-12 evening review: the second round ran 16-19 thousand characters).
        room = max(MAX_PAYLOAD_CHARS // 2, MAX_PAYLOAD_CHARS - len(note))
        return instructions + wrap_in_inert_boundary(_fitted(data, lessons, room), "scene-rewrite")

    stored = context["package"]
    rounds: list[dict[str, Any]] = []
    review: dict[str, Any] = {}
    package: dict[str, Any] = {}
    visual = context["visual_prompt"]
    for number in range(1, REWRITES_PER_RUNG + 1):
        # His refused words and her review of them (or: the picture's words did not change).
        note = _second_rewrite_note(rounds[-1]) if rounds else ""
        written = _editor_rewrite(
            engine, registry, editor_id, context, brief, asked(note) + note, correlation_id
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
                # The movement said once more as it was stored: the motion layer has nothing
                # else to say for this finding (2026-10-12, f06808c9 scenes 3, 4, 7).
                return _second_rewrite_failed(
                    outcome,
                    "a dat din nou cuvintele de dinainte ale scenei.",
                    exhausted=layer == MOTION,
                )
            outcome["reason"] = "Rescrierea a dat același prompt; nimic nou de cumpărat."
            # The caller may try the other layer: a motion rewrite that changed nothing on a
            # picture that stays is the picture's turn (MOTION_REWRITES_BEFORE_STILL).
            outcome["same_prompt"] = True
            return outcome
        if layer == STILL and not still_changed:
            # Her brief asked for the picture and the picture's words came back as they were:
            # no review on the motion's terms (2026-10-12 evening review of a50407e); he is
            # asked once more, told so, and a second time stores nothing.
            rounds.append(_unchanged_still_record(number, written))
            outcome["review_attempts"] = rounds
            if len(rounds) < REWRITES_PER_RUNG:
                continue
            outcome["not_treating"] = True
            outcome["reason"] = (
                "Rescrierea nu tratează constatarea: brief-ul cerea imaginea, iar cuvintele "
                "imaginii nu s-au schimbat nici a doua oară; nu se cumpără nimic pe ea."
            )
            return outcome
        if rounds and _same_words(rounds[-1], visual, package):
            # The words she refused, asked again: they cannot treat what they did not.
            return _second_rewrite_failed(
                outcome,
                "a dat aceleași cuvinte pe care Directoarea le-a refuzat.",
                exhausted=rounds[-1]["layer"] == MOTION,
            )
        # Her review, before anything is stored, on the brief's own layer: does the rewrite
        # treat the finding? (Owner, 2026-10-12: «Nu ai cum să faci de 5 ori aceeași
        # greșeală!») A review that could not be made fails closed: nothing is bought on words
        # nobody verified.
        earlier = rounds[-1] if rounds and not rounds[-1].get("still_unchanged") else None
        review = _reviewed(
            engine, registry, context, brief, layer, package, visual, correlation_id, earlier, qc
        )
        rounds.append(_round_record(number, written, layer, review))
        outcome["review_attempts"] = rounds
        if review.get("verdict") is None and earlier is not None:
            # Her review of the second rewrite could not be read: her refusal of the first
            # stands, with its verdict, its cause and its reason (2026-10-12 review: the
            # unreadable second review erased the first one's MISSES).
            return _second_rewrite_failed(
                outcome,
                "verificarea ei nu a putut fi făcută "
                f"({review.get('reason') or 'fără motiv'}); nu se cumpără nimic pe ea.",
            )
        outcome.update(
            review_run_id=review.get("run_id"),
            review_verdict=review.get("verdict"),
            review_reason_ro=str(review.get("reason_ro") or ""),
            review_findings=list(review.get("findings") or []),
            review_observations=list(review.get("observations") or []),
            review_broken_lessons=list(review.get("broken_lessons") or []),
            review_cause=str(review.get("cause") or ""),
            review_lesson=str(review.get("lesson") or ""),
        )
        if review.get("verdict") == ACCEPTED_MINOR:
            return _accepted_minor(outcome, review)
        if review.get("verdict") != MISSES:
            break
        if review.get("locked_only"):
            # Every reason she refused it for is words this layer keeps: another rewrite on
            # it cannot treat them, so the layer's turn ends here.
            return _locked_on_layer(outcome, review, layer)
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
        from app.media.montage import keep_frozen  # noqa: PLC0415

        # The film's frozen pauses stay on the row: a rewrite changes a picture's words only.
        row.prompt_json = keep_frozen(package, stored)
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
                "layer": layer,
                "brief": {key: brief.get(key) for key in ("diagnosis", "avoid", "keep", "change")},
                "old_still_prompt": context["visual_prompt"],
                "still_prompt": visual,
                "old_motion_prompt": stored.get("motion_prompt"),
                "motion_prompt": package.get("motion_prompt"),
                "old_package": stored,
                "package": package,
                "run_id": outcome["run_id"],
                # Her review of the words stored. CONTRACT (2026-10-12): ``findings`` keeps, for
                # every finding quality control gave, its id, quality control's own words
                # (``qc_text``), her few words (``finding``), the new sentence that treats it
                # (``by``), ``treated``, ``why_not``, ``severity``, ``layer`` and ``accepted``
                # (`_kept_findings`). What the purchase that follows is checked against: every
                # treated finding and every untreated SERIOUS one must be gone from the new
                # still (and its clip); an untreated MINOR one is ``accepted`` — hers to accept,
                # never open, never blocking, never a reason to withdraw a lesson (the evening
                # contract of 2026-10-12). ``observations`` are hers beyond quality control's,
                # advisory. ``cause`` and ``lesson`` say why the defect appeared and the rule
                # drawn from it — stored unverified under ``run_id`` for the film's kind
                # (``lesson_scope``), confirmed or withdrawn by what the next picture shows;
                # ``rounds`` counts his rewrites in the rung, ``refused`` the ones she refused
                # before this one (each with its findings and why_not).
                "review": {
                    "verdict": review.get("verdict"),
                    "reason_ro": review.get("reason_ro"),
                    "findings": list(review.get("findings") or []),
                    "observations": list(review.get("observations") or []),
                    "run_id": review.get("run_id"),
                    "cause": str(review.get("cause") or ""),
                    "lesson": str(review.get("lesson") or ""),
                    "lesson_recorded": learned,
                    "lesson_scope": lesson_scope(context),
                    "lesson_provisional": True,
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
        layer=layer,
        old_still_prompt=context["visual_prompt"],
        still_prompt=visual,
        old_motion_prompt=stored.get("motion_prompt"),
        motion_prompt=package.get("motion_prompt"),
        lesson_recorded=learned,
        lesson_skipped=unlearned,
    )
    return outcome


# ------------------------------------------------------------------ the ladder

#: The subject of the developer's note about one scene (`note_for_developer`): one per scene.
DEVELOPER_NOTE_SUBJECT = "Defect de unealtă (pentru dezvoltator): scena {scene} din «{title}»"


def note_for_developer(
    engine: Engine,
    context: dict[str, Any],
    note: str,
    *,
    run_id: str | None,
    correlation_id: str,
) -> str | None:
    """A tool's defect the ladder cannot treat, kept for the developer in the Director's own
    thread and resolved at once (`agents.director.DEVELOPER_DEFECT_KIND`, as her review keeps
    one): ONE per scene, so a scene asked again says nothing twice. Returns the note's id, or
    None when the scene was already noted (or no Director is there to write it).

    2026-10-12 evening review of a50407e: a lock on the still layer, or a motion that cannot
    treat a finding on a still the Owner approved, waited silently and was asked again every
    retry — nobody was told that only the composer's code (or he) could move it. The Owner's
    rule of that day: a tool's defect goes to the developer, never to him."""
    from app.agents.director import DEVELOPER_DEFECT_KIND  # noqa: PLC0415 - agents import media
    from app.agents.messages import post_message, resolve_message  # noqa: PLC0415
    from app.agents.models import AgentMessage  # noqa: PLC0415

    storyboard_id, index = str(context["storyboard_id"]), int(context["scene_index"])
    subject = DEVELOPER_NOTE_SUBJECT.format(scene=index, title=str(context["title"]))
    try:
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            for row in session.scalars(select(AgentMessage).where(AgentMessage.subject == subject)):
                body = row.body_json if isinstance(row.body_json, dict) else {}
                if (
                    body.get("kind") == DEVELOPER_DEFECT_KIND
                    and body.get("storyboard_id") == storyboard_id
                    and body.get("scene_index") == index
                ):
                    return None
            director = agent_for_role(session, "Director")
            if director is None:
                return None
            row = post_message(
                session,
                intent="STATUS",
                subject=subject,
                body={
                    "kind": DEVELOPER_DEFECT_KIND,
                    "storyboard_id": storyboard_id,
                    "scene_index": index,
                    "note": note,
                },
                body_text=note,
                from_agent_id=director.id,
                to_agent_id=director.id,
                run_id=run_id,
                correlation_id=correlation_id,
            )
            resolve_message(
                session,
                row.id,
                resolution="Notat pentru dezvoltator.",
                resolved_by=director.display_name,
                status="RESOLVED",
                correlation_id=correlation_id,
            )
            return str(row.id)
    except Exception as exc:  # noqa: BLE001 - the scene waits either way; only the note is lost
        logger.warning("developer_note_not_written", extra={"error": type(exc).__name__})
        return None


def _after(first: Any, second: Any) -> bool:
    """Whether the ISO moment ``first`` is later than ``second`` (as `utc_now` writes them)."""
    from datetime import datetime  # noqa: PLC0415

    try:
        a, b = datetime.fromisoformat(str(first)), datetime.fromisoformat(str(second))
    except (TypeError, ValueError):
        return str(first or "") > str(second or "")
    if (a.tzinfo is None) != (b.tzinfo is None):
        return str(first or "") > str(second or "")
    return a > b


def _composer_sentences() -> tuple[str, ...]:
    """Today's fixed sentences of the composer, whatever a stored prompt carries: a lock in
    one of them lasts while the composer still says it (`scene_waits`). The serial's life
    sentence is not one since 2026-10-16: the plan says whether it is said
    (`prompt_agent.serial_life_sentence`), so a lock on it lifts and she is asked again."""
    from app.media import prompt_agent as words  # noqa: PLC0415 - it imports us

    return (
        words.MEASURED_SENTENCE,
        words.FACES_CONSTRAINT,
        words.SERIAL_CAST_TAIL,
        words.SERIAL_FACES_SENTENCE,
        words.SERIAL_LISTEN_TAIL,
        words.SERIAL_FRAME_SENTENCE,
        words.SERIAL_BLANK_SENTENCE,
        words.COMPOSITION_SENTENCE,
        words.STILL_EXCLUSIONS,
        lint.MOTION_CLOSING,
        lint.VEO_MOTION_CLOSING,
    )


def _source_words_fingerprint(context: dict[str, Any]) -> str:
    """Stable identity of the exact scene package Sarah asked Kael to repair."""
    source = {
        "prompt_json": context.get("package") or {},
        "visual_prompt": context.get("visual_prompt") or "",
        "scene_index": context.get("scene_index"),
    }
    data = json.dumps(source, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _repeated_review_refusals(
    briefs: Sequence[dict[str, Any]],
    source_fingerprint: str,
    *,
    newer_take_than: Any = None,
) -> bool:
    """True only after two consecutive failed rungs on exactly unchanged prompts.

    A passed/stored rewrite, a missing fingerprint (older events), a new take or
    a different prompt resets the count. Never blocks the first correction.
    """
    count = 0
    for payload in briefs:
        if payload.get("source_words_fingerprint") != source_fingerprint:
            return False
        if payload.get("rewritten") or payload.get("resumed") or payload.get("accepted_minor"):
            return False
        timestamp = payload.get("_event_timestamp")
        if timestamp is None:
            return False
        if newer_take_than is not None and _after(newer_take_than, timestamp):
            return False
        failed = (
            payload.get("not_treating")
            or payload.get("same_prompt")
            or payload.get("review_unavailable")
            or payload.get("review_verdict") == MISSES
        )
        if not failed:
            return False
        count += 1
        if count >= MAX_UNCHANGED_REFUSED_RUNGS:
            return True
    return False


def scene_waits(engine: Engine, context: dict[str, Any]) -> str | None:
    """Why the ladder must not ask the Director the same brief again for this scene, in words;
    None when it may ask. 2026-10-12 evening review of a50407e: a scene her rung left where no
    rewrite can move it was asked the same thing at every retry of the walk and of the
    watchdog's ladder pass, and answered the same.

    It waits when her newest attempt for the scene ended (a) locked in the composer's own
    sentences (``composer_locked``) while those words are still the composer's — a fix of the
    composer lifts it — or (b) with the motion exhausted on a still the Owner approved (no
    rewrite may change his picture). Nothing waits once quality control refused a newer take
    of the scene, or the scene's words were rewritten since: something changed, so she is
    asked again."""
    from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT  # noqa: PLC0415

    storyboard_id, index = str(context["storyboard_id"]), int(context["scene_index"])
    with Session(engine) as session:
        newest = None
        rewritten_since = False
        same_source_briefs: list[dict[str, Any]] = []
        for event in session.scalars(
            select(DomainEvent)
            .where(
                DomainEvent.aggregate_id == storyboard_id,
                DomainEvent.event_type.in_((BRIEF_EVENT, SCENE_PROMPTS_REWRITTEN_EVENT)),
            )
            .order_by(DomainEvent.sequence.desc())
        ):
            if _payload(event).get("scene_index") != index:
                continue
            if event.event_type == BRIEF_EVENT:
                newest = event
                break
            rewritten_since = True
        if newest is None or rewritten_since:
            return None
        payload = _payload(newest)
        if any(
            row.status == "REJECTED"
            and row.failure_code in QUALITY_CODES
            and _after(row.created_at, newest.timestamp)
            for row in scene_takes(session, storyboard_id, index)
        ):
            return None
        his = _owner_still(session, storyboard_id, index)
        # The most recent brief and older rounds on unchanged words, at most
        # the two needed to recognise a futile repeated dialogue.
        for event in session.scalars(
            select(DomainEvent)
            .where(DomainEvent.aggregate_id == storyboard_id, DomainEvent.event_type == BRIEF_EVENT)
            .order_by(DomainEvent.sequence.desc())
            .limit(50)
        ):
            item = _payload(event)
            if item.get("scene_index") != index:
                continue
            same_source_briefs.append({**item, "_event_timestamp": event.timestamp})
            if len(same_source_briefs) >= MAX_UNCHANGED_REFUSED_RUNGS:
                break
        latest_take_time = next(
            (row.created_at for row in scene_takes(session, storyboard_id, index)), None
        )
    if _repeated_review_refusals(
        same_source_briefs,
        _source_words_fingerprint(context),
        newer_take_than=latest_take_time,
    ):
        return (
            f"Scena {index} așteaptă: Sarah a refuzat de două ori rescrieri pe "
            "același prompt, fără un take nou sau o corecție salvată între ele. "
            "Nu o mai trimit pe Kael în aceeași buclă; următorul pas este "
            "o schimbare verificabilă a scenei ori privirea a doua a Directoarei."
        )
    if payload.get("composer_locked"):
        kept = (
            *lock_texts(context, str(payload.get("layer") or MOTION))["constants"],
            *_composer_sentences(),
        )
        if any(words_kept(quote, kept) for quote in payload.get("locked_words") or []):
            return (
                f"Scena {index} așteaptă: refuzul controlului stă în propozițiile fixe ale "
                "compozitorului de prompturi, notate pentru dezvoltator, iar preluarea e la "
                "privirea a doua a Directoarei; nu o mai întreb același lucru."
            )
        return None
    if payload.get("layer_exhausted") and payload.get("layer") == MOTION and his:
        return (
            f"Scena {index} așteaptă: mișcarea nu poate trata ce a refuzat controlul, iar "
            "imaginea ei e aprobată de Proprietar și nu se rescrie; e notată pentru dezvoltator "
            "și preluarea e la privirea a doua a Directoarei; nu o mai întreb același lucru."
        )
    return None


def _refused_take_id(engine: Engine, storyboard_id: str, scene_index: int) -> str | None:
    """The scene's newest take quality control refused: the one her second look is about."""
    with Session(engine) as session:
        return next(
            (
                str(row.id)
                for row in scene_takes(session, storyboard_id, scene_index)
                if row.status == "REJECTED" and row.failure_code in QUALITY_CODES
            ),
            None,
        )


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
                subject=f"Rescrie scena {index} din «{context['title']}»",
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
                        + str(rounds[0].get("reason_ro") or "")
                        + ")"
                    )
                answer = (
                    f"Am rescris scena {index} ({redone}){again}. "
                    f"Promptul nou de mișcare: {str(done.get('motion_prompt') or '')}"
                )
            elif done.get("accepted_minor"):
                # Every finding minor (2026-10-12 evening): she accepts the take as it is.
                answer = (
                    f"Am rescris scena {index}, dar nu se cumpără nimic pe rescriere. "
                    f"{done.get('reason')}"
                )
            elif done.get("layer_exhausted"):
                # The motion layer cannot treat what quality control refused (2026-10-12,
                # f06808c9 scenes 3, 4, 7): the letter says the picture's turn has come.
                turn = (
                    # A still the Owner approved is never rewritten (2026-10-12 evening).
                    "imaginea e aprobată de Proprietar, așa că preluarea merge la privirea a "
                    "doua a Directoarei"
                    if done.get("second_look")
                    else "e rândul imaginii"
                )
                answer = (
                    f"Am rescris mișcarea scenei {index}, dar Directoarea a refuzat rescrierea: "
                    "stratul mișcării nu poate trata ce a refuzat controlul, așa că nu se "
                    f"cumpără nimic pe ea și {turn}. {done.get('reason')}"
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
                subject=f"Re: Rescrie scena {index} din «{context['title']}»",
                body={
                    "storyboard_id": context["storyboard_id"],
                    "scene_index": index,
                    "layer": done.get("layer"),
                    "rewritten": bool(done.get("rewritten")),
                    "prompts_before": {
                        "still": context["package"].get("still_prompt") or context["visual_prompt"],
                        "motion": context["package"].get("motion_prompt") or "",
                    },
                    "prompts_after": {
                        "still": done.get("still_prompt") or context["visual_prompt"],
                        "motion": done.get("motion_prompt") or "",
                    },
                    "review_attempts": rounds,
                },
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
                "source_words_fingerprint": _source_words_fingerprint(context),
                "layer": done.get("layer") or brief.get("layer"),
                "asked_layer": brief.get("layer"),
                "rewritten": bool(done.get("rewritten")),
                "resumed": bool(done.get("resumed")),
                "action": brief.get("action") or "rewrite",
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
                "review_unavailable": bool(done.get("review_unavailable")),
                # The motion layer could not treat the findings: counted as a motion attempt by
                # `open_layers`, so the picture's turn comes (2026-10-12, f06808c9 3, 4, 7).
                "layer_exhausted": bool(done.get("layer_exhausted")),
                "locked_findings": done.get("locked_findings") or [],
                # Nothing bought, the take to her second look (2026-10-12 evening): every
                # finding minor and accepted, or locked in the composer's own sentences — the
                # words kept so `scene_waits` knows when a fix of the composer lifts it.
                "accepted_minor": bool(done.get("accepted_minor")),
                "accepted_minor_ids": done.get("accepted_minor_ids") or [],
                "composer_locked": bool(done.get("composer_locked")),
                "locked_words": done.get("locked_words") or [],
                "second_look": bool(done.get("second_look")),
                "refused_take_id": done.get("refused_take_id"),
                "developer_note_id": done.get("developer_note_id"),
                # Quality control's findings her review answered, each by its id.
                "qc_findings": done.get("qc_findings") or [],
                "observations": done.get("review_observations") or [],
                "broken_lessons": done.get("review_broken_lessons") or [],
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
                    f"Scene {context['scene_index']} of “{context['title']}” "
                    + (
                        "failed delivery"
                        if brief.get("action") == "retry_delivery"
                        else "failed quality control"
                    )
                    + f": {brief.get('diagnosis')} — {brief.get('action') or 'rewrite'} "
                    f"{brief.get('layer')}, avoid " + "; ".join(brief.get("avoid") or [])
                ),
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
    if stored.get("prompt_format") == "editor_final_v1":
        # Old compositor recomposition would silently change Kael's reviewed
        # vendor text and orphan any corresponding paid media.
        return None
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


def recomposed_layer(rewrite: dict[str, Any]) -> str:
    """The layer a serial scene's words said again decide about: ``still`` when the picture's
    words changed (the stills step buys again on them, then the clip), ``motion`` when only the
    clip's did — the picture stays as it was bought. 2026-10-16: the composer's faces and life
    sentences changed the motion words of every serial shot and the picture words of none but
    the establishing ones; said again as ``still``, each refused clip would have bought its
    unchanged picture again."""
    old = " ".join(str(rewrite.get("old_still_prompt") or "").split())
    new = " ".join(str(rewrite.get("still_prompt") or "").split())
    return STILL if old != new else MOTION


def _say_serial_words_again(
    session: Session,
    target: StoryboardScene,
    rewrite: dict[str, Any],
    correlation_id: str,
) -> str:
    """A serial scene's words as today's composer says them, stored and written as the
    Director's decision on the scene (`SCENE_PROMPTS_REWRITTEN_EVENT`, on the layer whose words
    changed, `recomposed_layer`: ``still`` — the scene's hold lifts and the stills step buys
    again on the new words — or ``motion`` when the picture's words are unchanged). Inside the
    caller's write transaction; returns the layer."""
    from app.media.assembler import (  # noqa: PLC0415 - a large module
        DIRECTOR_REWRITE,
        SCENE_PROMPTS_REWRITTEN_EVENT,
    )
    from app.media.montage import keep_frozen  # noqa: PLC0415

    layer = recomposed_layer(rewrite)
    # The film's frozen pauses stay on the row: a rewrite changes a picture's words only.
    target.prompt_json = keep_frozen(dict(rewrite["package"]), target.prompt_json)
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
            "layer": layer,
            "camera_move": rewrite["package"].get("camera_move"),
        },
        correlation_id,
    )
    return layer


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
        layer = _say_serial_words_again(session, target, rewrite, correlation_id)
    outcome.update(
        rewritten=True,
        layer=layer,
        reason=SERIAL_RECOMPOSE_REASON,
        summary_ro=(
            f"Scena {scene_index} a serialului a fost compusă din nou cu cuvintele de azi "
            "(un singur moment, încadrare fixă); imaginea se reface."
            if layer == STILL
            else f"Scena {scene_index} a serialului a fost compusă din nou cu cuvintele de azi; "
            "imaginea rămâne, se reface doar mișcarea."
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
    with Session(engine) as session:
        delivery = last_failure_code(session, storyboard_id, scene_index) in DELIVERY_CODES
    if not delivery and _serial_scene(engine, storyboard_id):
        said = recompose_serial_scene(engine, storyboard_id, scene_index, correlation_id)
        if not said.get("needs_brief"):
            return said
    context = scene_context(engine, storyboard_id, scene_index)
    if context is None:
        outcome["reason"] = (
            "Scena nu este una pe care studioul o rescrie (card, film închis, fără plan)."
        )
        return outcome
    if context["last_code"] not in (*QUALITY_CODES, *DELIVERY_CODES):
        outcome["reason"] = "Scena nu a fost refuzată de controlul calității."
        return outcome
    if context["local_move"] and context["last_code"] != STILL_GATE_CODE:
        outcome["reason"] = "Proprietarul a ales mișcare locală pentru scenă."
        return outcome
    if not context["layers"]:
        outcome["reason"] = "Imaginea scenei este aprobată de Proprietar; nimic de rescris."
        return outcome
    waits = scene_waits(engine, context)
    if waits:
        # Her last rung left the scene where no rewrite can move it, and nothing changed since:
        # she is not asked the same brief again at every retry (2026-10-12 evening review of
        # a50407e); the take is still hers to look at.
        outcome.update(
            reason=waits,
            waiting=True,
            second_look=True,
            refused_take_id=_refused_take_id(engine, storyboard_id, scene_index),
        )
        return outcome
    done = _rung(engine, registry, context, dict(outcome), correlation_id)
    if not done.get("layer_exhausted"):
        return done
    # The motion layer could not treat the findings (2026-10-12, f06808c9 scenes 3, 4, 7: her
    # review named the beat's action and the move's fixed sentence, and nothing turned to the
    # picture): the picture's turn now, in the same call, when the still is open — her brief
    # reads the attempt just recorded, so `open_layers` opens only the still.
    again = scene_context(engine, storyboard_id, scene_index)
    if again is None or STILL not in again["layers"]:
        return done
    again["layers"] = (STILL,)
    again["layers_note"] = (
        "The movement was rewritten and your review found that what quality control refused is "
        "in words the motion layer keeps (the picture, the kept action or the composer's fixed "
        "sentences): only still is open, so the picture is described again."
    )
    escalated = _rung(engine, registry, again, dict(outcome), correlation_id)
    escalated["escalated_from"] = MOTION
    escalated["motion_reason"] = str(done.get("reason") or "")
    return escalated


def film_failure(reasons: list[Any]) -> dict[str, Any]:
    """The finished film's refusal of one scene as a brief reads it: {"kind": "film", "code":
    "QC.FILM", "reasons": [the findings' words], "causes": [each one's cause, or ""], "cause":
    the cause said for the scene as a whole}.

    The reasons a redo hands `rewrite_for_redo` are the Director's and the report's words about
    the scene and, since 2026-10-12, her verdict's cause — why the defect appeared — so the
    brief starts from it rather than diagnosing again: a dict {"text" | "finding" | "reason",
    "cause"}, a finding with its cause after a «cauza:» / «cause:» label, or a cause on its
    own (a line that begins with the label), which is the scene's.

    Only what was SEEN becomes a finding (`fix_check.observed`): her repair proposals («the
    motion must be redone on the new still …»), her second look's words before the purchase
    («Directoarea a privit din nou scena: …») and the studio's notes (`runbook.stages`'
    SAME_PROMPT_NOTE, LAYER_EXHAUSTED_NOTE) are her brief's ``context``, never a finding with
    an id that decides the review (2026-10-12 evening review of a50407e)."""
    from app.media.fix_check import observed  # noqa: PLC0415 - it imports us

    texts: list[str] = []
    causes: list[str] = []
    scene: list[str] = []
    context: list[str] = []
    for reason in reasons or []:
        if isinstance(reason, dict):
            text = _norm(reason.get("text") or reason.get("finding") or reason.get("reason"))
            cause = _norm(reason.get("cause"))
        else:
            text, cause = _norm(reason), ""
            label = _CAUSE_LABEL.search(text)
            if label is not None:
                text, cause = text[: label.start()].strip(" ;,.—–-("), text[label.end() :]
                cause = cause.strip(" )")
        seen = _norm(observed(text)) if text and _is_finding(text) else ""
        if not seen:
            if text and text.casefold() not in {said.casefold() for said in context}:
                context.append(text)
            if cause and cause not in scene:
                scene.append(cause)
            continue
        if seen.casefold() in {said.casefold() for said in texts}:
            continue
        texts.append(seen)
        causes.append(cause)
    failure: dict[str, Any] = {
        "kind": "film",
        "code": "QC.FILM",
        "reasons": texts,
    }
    if any(causes):
        failure["causes"] = causes
    if scene:
        failure["cause"] = " ".join(scene)
    if context:
        failure["context"] = context
    return failure


def rewrite_for_redo(
    engine: Engine,
    registry: Any,
    storyboard_id: str,
    scene_index: int,
    layer: str,
    reasons: list[Any],
    correlation_id: str,
) -> dict[str, Any]:
    """Before a paid redo the Director decided after the finished film failed QC: her brief
    from the report's words about the scene (``reasons``: her own, the report's and her
    verdict's cause, `film_failure`), the Video Editor's rewrite on ``layer`` (still: the
    picture and its motion; motion: the movement), her review against those findings.
    «Nu reface pur și simplu imaginea, trebuie verificat promptul și corectat!» The outcome's
    ``layer_exhausted`` tells the caller a motion rewrite cannot treat them (the picture's
    turn, as on ``same_prompt``).

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
    # A newer undelivered attempt is history, not the cause of the delivered film's QC.
    # Its journal is unchanged; never instruct a visual rewrite to retry that delivery.
    context.pop("delivery_failure", None)
    context["last_code"] = "QC.FILM"
    context["failures"] = [film_failure(reasons), *context["failures"]]
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
    if asked["brief"].get("action") == "retry_delivery":
        done = _authorize_delivery_retry(engine, context, asked, correlation_id)
        _record_brief(engine, context, asked, done, done.get("message_id"), correlation_id)
        outcome.update(done)
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
    unmovable = _unmovable(engine, context, done)
    if unmovable:
        # No rewrite can treat it (2026-10-12 evening review of a50407e): one note for the
        # developer per scene, nothing bought, and the take to her second look, which accepts
        # it or decides.
        done["second_look"] = True
        if done.get("layer_exhausted"):
            # His picture is never rewritten: the picture's turn does not come.
            done["reason"] = str(done.get("reason") or "").replace(
                _LAYER_EXHAUSTED_RO, _OWNER_STILL_RO
            )
        done["developer_note_id"] = note_for_developer(
            engine,
            context,
            unmovable,
            run_id=done.get("review_run_id"),
            correlation_id=correlation_id,
        )
    if done.get("second_look"):
        done["refused_take_id"] = _refused_take_id(
            engine, str(context["storyboard_id"]), int(context["scene_index"])
        )
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
        # The motion layer cannot treat the findings: the caller turns to the picture, as on
        # ``same_prompt`` (2026-10-12, f06808c9 scenes 3, 4, 7).
        layer_exhausted=bool(done.get("layer_exhausted")),
        review_verdict=done.get("review_verdict"),
        review_reason_ro=str(done.get("review_reason_ro") or ""),
        # His rewrites in the rung (a second one after her review refused the first) and
        # whether her lesson became the studio's (2026-10-12).
        review_rounds=len(done.get("review_attempts") or []),
        lesson_recorded=bool(done.get("lesson_recorded")),
        # CONTRACT (2026-10-12 evening): nothing was bought and the take is the caller's to
        # hand to her second look (``second_look``, ``refused_take_id``) — every finding was
        # minor and she accepts the take as it is (``accepted_minor``, with their ids), or no
        # rewrite can treat it: the composer's own sentences (``composer_locked``, with the
        # ``locked_words``) or a motion that cannot treat it on a still the Owner approved.
        accepted_minor=bool(done.get("accepted_minor")),
        accepted_minor_ids=list(done.get("accepted_minor_ids") or []),
        composer_locked=bool(done.get("composer_locked")),
        locked_words=list(done.get("locked_words") or []),
        second_look=bool(done.get("second_look")),
        refused_take_id=done.get("refused_take_id"),
        developer_note_id=done.get("developer_note_id"),
    )
    return outcome


def _unmovable(engine: Engine, context: dict[str, Any], done: dict[str, Any]) -> str | None:
    """The developer's note when the rung ended where no rewrite can treat the findings (the
    composer's own sentences on any layer, or a motion exhausted on a still the Owner
    approved: his picture is never rewritten), else None."""
    index, title = context["scene_index"], str(context["title"])
    blocking = set(done.get("locked_findings") or [])
    said = [
        _cut(item.get("qc_text"), 200)
        for item in done.get("qc_findings") or []
        if isinstance(item, dict) and (not blocking or item.get("id") in blocking)
    ]
    found = "; ".join(f"«{text}»" for text in said if text) or "fără cuvintele controlului"
    words = "; ".join(f"«{_cut(text, 160)}»" for text in done.get("locked_words") or [])
    if done.get("composer_locked"):
        return (
            f"Scena {index} din «{title}»: ce a refuzat controlul calității ({found}) stă în "
            f"propozițiile fixe ale compozitorului de prompturi ({words or 'fără citat'}), pe care "
            "nicio rescriere a scenei nu le poate schimba. Trebuie corectat compozitorul "
            "(app.media.prompt_agent) sau regula lui; nu s-a cumpărat nimic, iar preluarea e la "
            "privirea a doua a Directoarei."
        )
    if not done.get("layer_exhausted") or done.get("layer") != MOTION:
        return None
    with Session(engine) as session:
        if not _owner_still(session, str(context["storyboard_id"]), int(index)):
            return None
    return (
        f"Scena {index} din «{title}»: mișcarea nu poate trata ce a refuzat controlul calității "
        f"({found}){f', cerut de {words}' if words else ''}, iar imaginea scenei e aprobată de "
        "Proprietar și nu se rescrie. Nu s-a cumpărat nimic; preluarea e la privirea a doua a "
        "Directoarei."
    )


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
    recovered: list[dict[str, Any]] = []
    left: list[dict[str, Any]] = []
    for index in sorted(set(int(scene) for scene in scenes)):
        outcome = rewrite_failed_scene(engine, registry, storyboard_id, index, correlation)
        target = (
            rewritten if outcome["rewritten"] else recovered if outcome.get("resumed") else left
        )
        target.append(outcome)
    if rewritten or left:
        logger.info(
            "director_ladder",
            extra={
                "storyboard_id": storyboard_id,
                "rewritten": [item["scene_index"] for item in rewritten],
                "left": [item["scene_index"] for item in left],
            },
        )
    return {"rewritten": rewritten, "recovered": recovered, "not_rewritten": left}


def quality_refused(engine: Engine, storyboard_id: str, scenes: list[int]) -> list[int]:
    """Scenes for the Director: visual refusals or a known terminal delivery failure.
    Accounts and ambiguous submissions retain their existing recovery/Owner gates."""
    with Session(engine) as session:
        return [
            index
            for index in sorted(set(int(scene) for scene in scenes))
            if last_failure_code(session, storyboard_id, index) in (*QUALITY_CODES, *DELIVERY_CODES)
        ]


def _authorize_delivery_retry(
    engine: Engine, context: dict[str, Any], asked: dict[str, Any], correlation_id: str
) -> dict[str, Any]:
    """Release a terminal undelivered take's step hold after Sarah's decision, buying nothing.
    The takes, request journal, costs and paid-attempt counts remain evidence. A changed,
    in-flight or unproven request is never released; the normal staircase prices the retry.
    """
    from app.agents.messages import post_message, resolve_message  # noqa: PLC0415
    from app.agents.models import AgentMessage  # noqa: PLC0415
    from app.media.assembler import (  # noqa: PLC0415
        DELIVERY_RETRY_EVENT,
        MOTION_HOLD_EVENT,
        STILL_HOLD_EVENT,
        _paid_attempts,
        max_paid_attempts_per_scene,
    )
    from app.media.renders_cap import renders_per_layer, renders_ro  # noqa: PLC0415
    from app.media.shooting_sheet import film_is_closed  # noqa: PLC0415
    from app.providers.runpod.jobs import GenerationJob  # noqa: PLC0415

    result: dict[str, Any] = {
        "rewritten": False,
        "resumed": False,
        "layer": asked["brief"]["layer"],
        "reason": "",
    }
    board, index = str(context["storyboard_id"]), int(context["scene_index"])
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        failure = context.get("delivery_failure") or {}
        planned = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == board, StoryboardScene.scene_index == index
            )
        )
        if planned is None or dict(planned.prompt_json or {}) != context["package"]:
            result["reason"] = "Promptul scenei s-a schimbat; Directoarea recitește noul plan."
            return result
        take = session.get(SceneTake, str(failure.get("take_id") or ""))
        if (
            film_is_closed(session, board)
            or take is None
            or take.status != "REFUSED"
            or take.failure_code not in DELIVERY_CODES
            or take.path
            or take.sha256
            or last_failure_code(session, board, index) != take.failure_code
        ):
            result["reason"] = (
                "Scena s-a schimbat; Directoarea recitește situația înainte de reluare."
            )
            return result
        newest = next(
            (
                row
                for row in scene_takes(session, board, index)
                if row.failure_code in DELIVERY_CODES
            ),
            None,
        )
        if newest is None or newest.id != take.id:
            result["reason"] = "Înregistrarea refuzată s-a schimbat; reluarea nu este autorizată."
            return result
        job = (
            session.scalar(
                select(GenerationJob).where(
                    GenerationJob.remote_job_id == take.remote_task_id,
                    GenerationJob.project_id == board,
                    GenerationJob.scene_id == str(index),
                )
            )
            if take.remote_task_id
            else None
        )
        if (
            job is None
            or job.status != "FAILED"
            or job.asset_path
            or job.asset_sha256
            or job.error_code != "EXPIRED_UNDELIVERED"
        ):
            result["reason"] = (
                "Directoarea a preluat livrarea; jurnalul nu confirmă încă un eșec terminal "
                "fără fișier. Nu se trimite o cerere duplicată."
            )
            return result
        kinds = ("still",) if take.kind == "still" else ("test_shot", "motion")
        group = "still" if take.kind == "still" else "shot"
        attempts = _paid_attempts(
            [row for row in scene_takes(session, board, index) if row.kind in kinds], group
        )
        if attempts >= renders_per_layer():
            # The Owner's renders cap (2026-10-16, «maxim încă o randare»): a retry of the
            # delivery would be one more render of the layer, and none is bought past it.
            result["reason"] = (
                f"Directoarea a preluat livrarea; stratul are deja {renders_ro(attempts)}, "
                f"plafonul Proprietarului fiind de {renders_ro()}: nu se mai cumpără o reluare. "
                "Numărul de încercări plătite se păstrează."
            )
            return result
        if attempts >= max_paid_attempts_per_scene():
            result["reason"] = (
                "Directoarea a preluat eșecurile repetate de livrare; trebuie remediat "
                "furnizorul înainte de altă cumpărare. Numărul de încercări plătite se păstrează."
            )
            return result
        prior = [
            e
            for e in session.scalars(
                select(DomainEvent).where(
                    DomainEvent.event_type == DELIVERY_RETRY_EVENT,
                    DomainEvent.aggregate_id == board,
                )
            )
            if (e.payload or {}).get("take_id") == take.id
        ]
        if prior:
            result.update(
                resumed=True, reason="Reluarea livrării este deja autorizată de Directoare."
            )
            return result
        hold_kind = STILL_HOLD_EVENT if take.kind == "still" else MOTION_HOLD_EVENT
        holds = [
            e.event_id
            for e in session.scalars(
                select(DomainEvent).where(
                    DomainEvent.event_type == hold_kind,
                    DomainEvent.aggregate_id == board,
                    DomainEvent.timestamp >= take.created_at,
                )
            )
            if (e.payload or {}).get("scene_number") == index
        ]
        words = str(asked["brief"]["summary_ro"])
        append_event(
            session,
            DELIVERY_RETRY_EVENT,
            "storyboard",
            board,
            1,
            {
                "scene_index": index,
                "scene_number": index,
                "take_id": take.id,
                "layer": result["layer"],
                "decided_by": DECIDED_BY,
                "released_event_ids": holds,
                "paid_attempts": attempts,
                "brief_run_id": asked.get("run_id"),
                "reason_ro": words,
            },
            correlation_id,
        )
        editor = agent_for_role(session, "VideoEditor")
        if editor is not None:
            message = post_message(
                session,
                intent="STATUS",
                subject=f"Reia livrarea scenei {index}: {context['title']}",
                body={
                    "kind": "delivery_retry_plan",
                    "storyboard_id": board,
                    "scene_index": index,
                    "take_id": take.id,
                },
                body_text=words + " Fluxul de producție reia cererea pe prompturile aprobate, "
                "după verificarea bugetului, aprobării și opririi GPU.",
                from_agent_id=asked.get("agent_id"),
                to_agent_id=editor.id,
                run_id=asked.get("run_id"),
                correlation_id=correlation_id,
            )
            resolve_message(
                session,
                message.id,
                resolution="Preluat de fluxul de producție; "
                "rezultatul generării rămâne de verificat.",
                resolved_by="Fluxul de producție",
                status="RESOLVED",
                correlation_id=correlation_id,
            )
            result["message_id"] = str(message.id)
        # Withdraw only obsolete editorial/technical questions, never spending approvals.
        for message in session.scalars(
            select(AgentMessage).where(
                AgentMessage.to_agent_id.is_(None), AgentMessage.status == "OPEN"
            )
        ):
            body = message.body_json or {}
            if (
                body.get("kind") == "owner_shooting_sheet"
                and body.get("storyboard_id") == board
                and body.get("status") == "NEEDS_OWNER"
                and body.get("step") == ("stills" if take.kind == "still" else take.kind)
                and not body.get("approval_id")
            ):
                resolve_message(
                    session,
                    message.id,
                    resolution="Directoarea a preluat remedierea "
                    "livrării; nu este necesară o decizie a Proprietarului.",
                    resolved_by="Director",
                    status="RESOLVED",
                    correlation_id=correlation_id,
                )
        result.update(resumed=True, reason=words)
    return result
