"""The stills step: the first, cheapest stair of the money staircase.

Nothing is animated until someone has looked at its still. The Nepal film (2026-09-26) paid
for twelve clips before anybody looked at a picture: three stills showed faces the visual
bible forbade, a bar chart came back as a woman, a black screen as a landscape, and the whole
film was then bought a second time with the same prompts. A still costs 9 credits at 2K; the
clip made from it up to 68 credits a second. So the still is bought first, on its own, and
judged before any motion is priced.

What this step does, in order, and what stops it:

1. The plan (`stills_plan`): every LIVE scene's still prompt exactly as it will be sent, the
   model (seedream5_pro), the ratio (1530:2720, i.e. 2K), the candidates per scene
   (`STILL_CANDIDATES`), the re-rolls the Owner's renders cap leaves (`renders_cap`), and the
   credits: the expected round and the cap (each scene's round as many times as its renders
   cap still allows it, never a render past it). A scene that already holds an APPROVED take
   for its prompt is not bought again and costs 0. Its sha256 is the plan_hash the Owner's yes
   is bound to.
2. Refusals before anything is asked or bought (`StillsStageRefused`, a 409 for the route):
   a plan_hash that is not the current plan's (STALE_PLAN); in PRODUCTION a LIVE scene whose
   prompt was not written by the model, or for the office serial composed from its fixed
   series look (NEEDS_SHOT_PLAN); an open lint BLOCK (LINT_BLOCKED);
   a Runway balance below the step's first round x 1.15 (the Owner's rule of 2026-10-03,
   `balance_rule`: the cap is the ceiling, not what the account must hold to start), or one
   that could not be read (LOW_BALANCE).
3. The Owner's gate: `may_act('media.stills_purchase', context={plan_hash, cap_credits})`.
   With no answer it is one ApprovalRequest (NEEDS_APPROVAL, a 202); his yes is spent there,
   in the same transaction, before the first image is bought. One yes buys one stills step
   of one plan.
4. The purchase: LIVE scenes only; a chart, a title or a black screen never reaches the image
   model. The first LIVE scene is bought first. Once one of its candidates passes, that still
   is Figure 1 (``referenceImages``) for every later scene, for its light, palette and grain
   only (`FIGURE_ONE`). If it never passes, no later scene is bought: buying them without the
   film's look would be buying blind.
5. Each candidate is a SceneTake (PAID) the moment it lands, then judged: the local checks
   first (`still_gate.local_checks`, 0 credits; YuNet faces among them), and only a candidate
   the local checks did not stop is shown to the vision model (`picture_qc.judge_still`).
   The best passing candidate is APPROVED (by ``still_gate``), a passing runner-up stays PAID
   for the Owner to pick on the contact sheet, a failing one is REJECTED with its reasons.
6. A scene with no passing candidate is bought again while the Owner's renders cap leaves
   room (`renders_cap.max_rerolls`: since 2026-10-16 the first render and at most one more),
   with what was wrong rewritten as positive words (`still_gate.positive_instruction`), then
   marked NEEDS_OWNER with a WARNING event. Since 2026-10-12 (the Owner: «LLM-ul este pe abonament!
   … GENERAREA DE IMAGINI ȘI MIȘCĂRI COSTĂ!») the Director looks first, for free, at the
   refused candidates the bible's hard limits did not stop (`_settle_round`): a candidate her
   look lets stand is approved by her and nothing more is bought; and a still that shows its
   corrected words and the corrected mistake again ends the scene for her ladder at once —
   never re-rolled on the words that did not correct it. Since the review of 5fc7468 (that
   night) a refusal of the WORDS she confirms goes to her ladder too, not to a blind re-roll
   (only a technical one is re-rolled), every refused take of such a round begins with the
   content phrase the ladder reads, and collected candidates are settled the same way. A
   vendor refusal follows its kind
   (`production_policy.classify_failure`): SAFETY is never resubmitted with the same words
   and the scene goes to the Owner; a transient failure is tried once more; an account
   problem or a second refused request in a row stops the step.
7. The cap binds inside the loop: before every request, the credits already committed plus
   that request's price must stay within the approved cap (STOPPED_AT_CAP otherwise). The
   balance is read before every request (it buys nothing) and must hold that request's price
   x the margin: when it does not, the scene stops cleanly (NEEDS_OWNER, failure_kind
   LOW_BALANCE, not held against the Owner), what was bought is kept and nothing more is
   bought in the step (`balance_rule.purchase_stop_ro`; the summary's ``low_balance``). The
   balance before and after gives the measured credits, written on each take and, with the
   Runway integration named, as MEASURED prices.

8. Every request is a SceneTake (SUBMITTED, with the vendor's task id) the moment the vendor
   accepts it, before any poll; its candidates land on it. A task whose stills do not arrive
   (the poll deadline, a poll or a download that fails) stays SUBMITTED, the scene IN_FLIGHT
   and the step stops: it is collected later by its id (a GET, free), at the start of the next
   step and by the watchdog, and never bought again. A candidate collected that way, or one
   whose process died before it was judged, is PAID and UNJUDGED; the scene is "pending" in
   the plan (not bought) and its candidates are judged first. When nothing else is to be
   bought, the day settles them on its own (`settle_stills`: no purchase, no yes asked).
9. A scene remembers what happened to it since the Owner last decided about it
   (`assembler.scene_memory`): a scene the gate or the vendor left to him is "held", out of
   every later purchase, until his decision on the sheet (2026-10-02: under his MODE rule
   such a scene had been bought again every day). Past `max_paid_attempts_per_scene` paid
   requests it waits for him too, whatever its prompt. While scene 1 (Figure 1) is held,
   nothing later is offered for purchase.
10. A scene showing a character with a reference picture is drawn from it: the identity of
   its still includes the picture (as `assemble_from_takes` reads it), the picture goes to the
   vendor as Figure 1 and the film's look as Figure 2 (`CHARACTER_FIGURE`, `FIGURE_TWO`). A
   character whose look is locked and who has no reference refuses the step, NEEDS_REFERENCE,
   before anything is asked or bought.

Nothing here ever asks a video model: the motion step is a separate approval.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.db import lock_for_write
from app.media import fix_check
from app.media.assembler import (
    CAP_APPROVER,
    DEFAULT_STORAGE_ROOT,
    FREE_FAILURE_KINDS,
    LIVE_KIND,
    NOT_QUEUED_DETAIL,
    NOT_QUEUED_REASON,
    STILL_HOLD_EVENT,
    STUDIO_DEFECT_KIND,
    UNANSWERED_FAILURE_CODE,
    UNANSWERED_REASON,
    UNCOUNTED_DROP_STOP,
    UNJUDGED_DETAIL,
    UNJUDGED_FAILURE_CODE,
    SpendMeter,
    _record_intent,
    budget_cut,
    classify_vendor_failure,
    collect_submitted_takes,
    failure_code_of,
    failure_detail_of,
    gpu_seconds_to_credits,
    identity_key,
    max_paid_attempts_per_scene,
    outcome_unknown,
    owner_rejected_takes,
    possibly_charged,
    recode_not_queued,
    record_take,
    runpod_hold_items,
    scene_kind_of,
    scene_memory,
    scene_reference,
    shot_plan_sources,
    still_fields,
    take_hash,
    uncounted_drop,
    usable_take,
)
from app.media.balance_rule import (
    DEFAULT_MARGIN,
    LOW_BALANCE,
    low_balance_record,
    needed_credits,
    purchase_stop_ro,
    start_refusal_ro,
)
from app.media.cost_plan import (
    STILL_CANDIDATES,
    STILLS_MODEL,
    STILLS_RESOLUTION,
    PriceTable,
    UnpricedError,
    load_price_table,
    price_still,
    source_label,
)
from app.media.disk import LOW_DISK, disk_refusal
from app.media.faces import FaceCounter
from app.media.fix_check import STILL_LAYER, open_findings
from app.media.markings import planned_markings
from app.media.mode_guard import PurchaseGuard, unasked_refusal
from app.media.models import SceneTake, Storyboard, StoryboardScene
from app.media.montage import FACTUAL_SIZES, beat_of
from app.media.picture_qc import StillJudgement, judge_still
from app.media.prepared_batch import RoundWork, purchase_flow
from app.media.prompt_lint import (
    BLOCK,
    LintScene,
    bible_face_rule,
    has_block,
    lint_film,
    summary_ro,
)
from app.media.renders_cap import (
    at_cap,
    renders_made,
    renders_of_ro,
    renders_per_layer,
    renders_ro,
)
from app.media.still_gate import (
    ALL_CHECKS,
    COLOUR_WORDS,
    REWRITE_PHRASE,
    StillPlan,
    StillReport,
    choose_best,
    content_refusal,
    decide,
    local_checks,
    may_be_overturned,
    measured_refusal,
    positive_instruction,
    rewrite_step,
    round_step,
)
from app.providers.media_http import MediaProviderError, TaskStillOpen
from app.providers.runpod.batch import (
    UNCERTAIN,
    BatchRequest,
    ItemOutcome,
    SubmittedItem,
    item_seed,
    supports_batch,
)
from app.providers.runpod.wiring import bind_scene, sync_take_quality

#: The Policy Kernel's name for this step, and the sheet step it is bound to.
STILLS_ACTION = "media.stills_purchase"
STILLS_STEP = "stills"
#: The vendor's ratio for a 2K 9:16 still (priced as STILLS_RESOLUTION, "2K").
STILL_RATIO = "1530:2720"
#: What a still must not become, said in the image model's negative channel (RunPod's worker
#: has one: `BatchRequest.negative_prompt` reaches the graph): the stills gate's refusals of
#: 2026-10-11/12 — the serial's two-shots drawn as stacked panels (scenes 3 and 6, twelve
#: refusals each), lettering drawn on a ledger — said where a negation belongs and never in
#: the positive prompt (ADR-POSITIVE-PROMPTS-ONLY). The plan's own `avoid` items join it; a
#: bible that forbids faces adds them. Not part of the still's identity: the words and the
#: reference picture are (`still_fields`), so an approved still stays approved.
STILL_NEGATIVE: tuple[str, ...] = (
    "split screen",
    "collage",
    "panels",
    "comic strip",
    "stacked frames",
    "diptych",
    "triptych",
    "grid of pictures",
    "text",
    "lettering",
    "captions",
    "subtitles",
    "logo",
    "watermark",
)
STILL_NEGATIVE_FACES: tuple[str, ...] = ("visible faces", "portrait")
#: The actual local request schema's limit; a 400-character aesthetic target used to
#: erase scene-specific corrections while retaining generic exclusions.
NEGATIVE_CHARS = 20000


def _bible_bans_faces(bible: Mapping[str, Any] | None) -> bool:
    from app.media.prompt_lint import BIBLE_NO_FACES  # noqa: PLC0415 - lint imports nothing of ours

    texts: list[str] = []
    for key in ("continuity_rules", "avoid"):
        value = (bible or {}).get(key)
        if isinstance(value, list):
            texts += [str(item) for item in value if item]
    for key in ("style", "notes", "realism"):
        value = (bible or {}).get(key)
        if isinstance(value, str):
            texts.append(value)
    return any(BIBLE_NO_FACES.search(text) for text in texts)


#: Of `STILL_NEGATIVE`, the terms a scene whose plan names an object with its own markings
#: leaves out (`markings.planned_markings`, 2026-10-13): a negative channel told «text,
#: lettering» beside «the thermometer keeps its scale» draws a blank instrument. Captions,
#: subtitles, a logo and a watermark stay out of every still.
_MARKED_OBJECT_KEEPS: frozenset[str] = frozenset({"text", "lettering"})


def still_negative(
    package: Mapping[str, Any] | None,
    bible: Mapping[str, Any] | None,
    markings: Sequence[str] = (),
) -> str:
    """The negative prompt of one still: `STILL_NEGATIVE` (without «text» and «lettering»
    when the plan names an object that carries its own markings, ``markings``), the faces
    when the bible forbids them, then the plan's own `avoid` items, each once, within
    `NEGATIVE_CHARS`."""
    terms: list[str] = [
        term for term in STILL_NEGATIVE if not (markings and term in _MARKED_OBJECT_KEEPS)
    ]
    if _bible_bans_faces(bible):
        terms += STILL_NEGATIVE_FACES
    for avoid in ((bible or {}).get("avoid"), (package or {}).get("avoid")):
        if not isinstance(avoid, list):
            continue
        for item in avoid:
            words = " ".join(str(item or "").split()).strip(" .;,").lower()
            if words and words not in terms:
                terms.append(words)
    said = ""
    for term in terms:
        more = term if not said else f"{said}, {term}"
        if len(more) > NEGATIVE_CHARS:
            raise StillsStageRefused(
                "NEGATIVE_PROMPT_TOO_LONG",
                "Condițiile imaginii depășesc limita cererii; "
                "scurtați-le fără a pierde corecțiile.",
            )
        said = more
    return said


#: The reviewer a still is approved by when the gate, not the Owner, chose it.
GATE_REVIEWER = "still_gate"
#: How a later scene is told what scene 1's still is for. English: it is for the model.
FIGURE_ONE = (
    "Use Figure 1 only for its light, palette and grain; do not copy its objects or composition."
)
#: The same, when the scene's character reference goes first and scene 1's still second.
FIGURE_TWO = (
    "Use Figure 2 only for its light, palette and grain; do not copy its objects or composition."
)
#: How a scene drawn from its character's reference picture is told what Figure 1 is.
CHARACTER_FIGURE = (
    "Figure 1 is the character reference of {name}: draw {name} with exactly this face, hair, "
    "outfit and colours; do not copy its background or its pose."
)
#: The account must hold this much more than the next purchase (the first round to start,
#: each request after it) before it is asked or bought (`balance_rule`).
BALANCE_MARGIN = DEFAULT_MARGIN
#: The failure code a candidate the studio's own gate rejected carries.
GATE_FAILURE_CODE = "LOCAL.STILL_GATE"
#: Failure kinds tried once more on the same words (production_policy.classify_failure).
RETRY_KINDS = ("TRANSIENT", "BAD_OUTPUT")
#: A still take that was bought and is not settled yet: its task still open at the vendor, or
#: its candidates on disk and not judged. Such a scene is not bought; it is collected or judged.
PENDING_STATUSES = ("SUBMITTED", "PAID")
#: Why a scene whose request the vendor accepted is not bought again, in the Owner's words.
IN_FLIGHT_REASON = (
    "Scena {scene}: furnizorul a primit deja cererea plătită pentru imaginile ei și nu le-a "
    "predat încă; se ridică fără o nouă cumpărare."
)
IN_FLIGHT_STOP = (
    "Scena {scene}: furnizorul a primit cererea plătită, dar imaginile nu au sosit încă; se "
    "ridică mai târziu, fără o nouă cumpărare. În acest pas nu se mai cumpără imagini."
)
#: The failure code of a task the vendor accepted and answered with fewer stills than asked.
NO_OUTPUT_CODE = "VENDOR.NO_OUTPUT"

Judge = Callable[..., StillJudgement]


class StillsStageRefused(RuntimeError):
    """The step did not buy anything. ``status`` says why; ``reason_ro`` is the Owner's.

    NEEDS_APPROVAL is a 202 for the route (the Owner has a question waiting, with
    ``approval_id``); every other status is a 409.
    """

    def __init__(
        self,
        status: str,
        reason_ro: str,
        *,
        approval_id: str | None = None,
        findings: Sequence[Any] = (),
        plan: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(reason_ro)
        self.status = status
        self.reason_ro = reason_ro
        self.approval_id = approval_id
        self.findings = list(findings)
        self.plan = plan

    @property
    def http_status(self) -> int:
        return 202 if self.status == "NEEDS_APPROVAL" else 409


#: A still the scene had made (a picture came back and was judged, kept or lost): what a new
#: round's re-rolls are seeded past. A request that made nothing is sent again as it was.
_MADE_STILL_STATUSES: tuple[str, ...] = ("PAID", "APPROVED", "REJECTED", "LOST")


@dataclass
class _Scene:
    """One scene as the step reads it."""

    index: int
    kind: str
    words: str
    identity: dict[str, Any]
    look_block: str
    camera_move: str
    source: str | None
    reuse: SceneTake | None = None
    #: Bought and not settled: SUBMITTED takes (task open) and UNJUDGED candidates on disk.
    pending: list[SceneTake] = field(default_factory=list)
    #: The character's reference picture the still is drawn from (with its bytes), or None.
    reference: dict[str, Any] | None = None
    #: Why the scene cannot be drawn at all: a locked character with no reference.
    needs_reference: str | None = None
    #: Why the scene waits for the Owner (`assembler.scene_memory`); never bought meanwhile.
    hold_ro: str | None = None
    #: Paid requests for the scene since the Owner last decided about it.
    attempts: int = 0
    #: Every still the scene ever had made (any identity; `_MADE_STILL_STATUSES`): the
    #: re-rolls of a new round are seeded past them, so the same words make different
    #: candidates (2026-10-12: a serial scene made again on today's words after a decision).
    rolls: int = 0
    #: How many times the scene's still has been made (`renders_cap.renders_made`): what the
    #: Owner's renders cap leaves of it sizes the step's cap.
    renders: int = 0
    #: What the still must not become (`still_negative`), for the model's negative channel.
    negative: str = ""
    #: What the scene asks for beside its prompt — its written picture, the narration over
    #: it, its purpose — for the gate's `shows_scene` question (`still_gate.StillPlan`). The
    #: written picture is the scriptwriter's line (`_scene_picture`), never the compiled prompt.
    picture: str = ""
    narration: str = ""
    purpose: str = ""
    #: What the scene's current words were rewritten to fix (`fix_check.open_findings`), for
    #: the gate to verify on every still bought for it (`still_gate.StillPlan.must_fix`).
    must_fix: tuple[dict[str, str], ...] = ()
    #: The plan's objects that carry their own markings (`markings.planned_markings`), for the
    #: gate (`still_gate.StillPlan.expected_markings`): a thermometer's scale is not writing.
    expected_markings: tuple[str, ...] = ()
    prompt_issues: tuple[str, ...] = ()
    #: The room the beat names (a serial scene's plan ``location``; empty for a factual
    #: scene): the film's Figure 1 goes only to a scene in its own room (`_references`).
    location: str = ""
    #: The shot's form when the montage cut a factual scene into shots (`montage_shot`):
    #: {"shot", "of", "size"}, for the gate (`still_gate.StillPlan.shot_form`); None otherwise.
    shot_form: dict[str, Any] | None = None


@dataclass
class _Ledger:
    """What the step has committed, against the approved cap. ``meter`` is the caller's
    (`assembler.SpendMeter`): the credits committed and the requests sent live there, so a
    caller reads them when the step raises half-way."""

    cap: int
    meter: SpendMeter = field(default_factory=SpendMeter)
    images: int = 0
    take_ids: list[str] = field(default_factory=list)
    #: The step's hold on the budgets (`shooting_sheet.StepHold`): its next round, grown before
    #: every later purchase. None (a scene redo, a direct call): the cap alone binds.
    hold: Any = None

    @property
    def committed(self) -> float:
        return self.meter.committed

    @committed.setter
    def committed(self, value: float) -> None:
        self.meter.committed = value

    def room(self, wanted: float = 0.0) -> float:
        """The credits the step may still commit: the cap's rest and, with a budget hold, no
        more than it covers once grown for ``wanted`` more (`StepHold.room`)."""
        rest = float(self.cap) - self.committed
        if self.hold is None:
            return rest
        return min(rest, float(self.hold.room(self.committed, wanted)))

    def round_room(self, price: float) -> None:
        """Before a round is fitted (`gpu_batch.run_rounds`): the hold grows to the round, or
        by what the budgets have left, and the round is cut to what is held. Asked for
        nothing (``price`` 0, RunPod measured more than estimated), it grows to what the step
        owes."""
        if self.hold is not None:
            self.hold.room(self.committed, price, partial=True)

    def hold_spent(self) -> None:
        """What the step committed is held at once (`StepHold.hold_spent`): a vendor's quote
        above the price is committed whole, and no other step reads it as free meanwhile."""
        if self.hold is not None:
            self.hold.hold_spent(self.committed)

    def budget_words(self, wanted: float | None = None) -> str | None:
        """The budget's words when the hold, not the cap, stopped the next purchase
        (``wanted`` credits, when known)."""
        if self.hold is None:
            return None
        if wanted is None:
            return self.hold.budget_words()
        return self.hold.budget_words(self.committed, wanted)


# ------------------------------------------------------------------------------ the plan


def _usd_ro(amount: float) -> str:
    """«2,16 USD»: an amount in the Owner's question, with a decimal comma."""
    return f"{float(amount):.2f}".replace(".", ",") + " USD"


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def is_serial_package(package: Mapping[str, Any] | None) -> bool:
    """Whether a scene's package was composed by the serial composer
    (`prompt_agent._serial_package`: the beat's people in frame and the shot's size)."""
    return isinstance((package or {}).get("in_frame"), list) and bool(
        (package or {}).get("shot_size")
    )


def serial_scene_picture(package: Mapping[str, Any]) -> str:
    """A serial scene's written picture: what the composer draws its still from — the beat's
    room, the people in frame (`in_frame`, as the beat puts them there) and the first moment of
    its action (`prompt_agent._still_moment`) — never the writer's line.

    2026-10-12, f06808c9 scene 1 (the review of 9ac0195, finding 4): ``writer_visual`` said
    «Marcus alone at his desk» while the composed beat put Marcus and Sarah in frame; a gate
    shown the writer's line refuses every correct still of the beat as «not the scene»."""
    from app.media.prompt_agent import (  # noqa: PLC0415 - large
        _short_name,
        _still_moment,
        partial_clothing_sentence,
        serial_partial_characters,
    )

    people = [
        _short_name(person.get("name"))
        for person in package.get("in_frame") or []
        if isinstance(person, Mapping) and person.get("name")
    ]
    location = " ".join(str(package.get("location") or "").split()).rstrip(". ")
    moment = " ".join(_still_moment(str(package.get("action") or "")).split()).rstrip(". ")
    parts = [
        f"{location}." if location else "",
        f"In frame: {', '.join(dict.fromkeys(people))}." if people else "",
        f"{moment[:1].upper()}{moment[1:]}." if moment else "",
    ]
    parts.extend(partial_clothing_sentence(person) for person in serial_partial_characters(package))
    return " ".join(part for part in parts if part)


def montage_shot(package: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The form of a factual shot the montage cut from a writer's scene (`montage.beat_tag`):
    ``{"shot": k, "of": n, "size": "wide" | "medium" | "detail"}``; None for a scene that is
    its own one shot (the montage off, a short scene, a card) and for a serial beat, whose
    picture is its own composed beat already (`serial_scene_picture`)."""
    if not package or is_serial_package(package):
        return None
    tag = beat_of(dict(package))
    shot, of, size = tag.get("shot"), tag.get("of"), str(tag.get("size") or "")
    if not isinstance(shot, int) or not isinstance(of, int) or of <= 1 or not 1 <= shot <= of:
        return None
    if size not in FACTUAL_SIZES:
        return None
    return {"shot": shot, "of": of, "size": size}


def factual_shot_picture(package: Mapping[str, Any]) -> str:
    """A factual montage shot's written picture: the Editor's subject for this shot and the
    first moment of its action (`prompt_agent._still_moment`, the moment its still is drawn
    from), as `serial_scene_picture` gives a serial beat its own; empty when the shot's plan
    names neither.

    2026-10-16, audit finding 27: every shot of a cut scene (wide, medium, detail) was judged
    against the writer's line for the WHOLE scene, so a right «detail: hands on the ledger»
    of a scene written as «a slow drift through a dark detector cavern» failed shows_scene and
    the Director's ladder bought it again."""
    from app.media.prompt_agent import _still_moment  # noqa: PLC0415 - large

    subject = " ".join(str(package.get("subject") or "").split()).rstrip(". ")
    moment = " ".join(_still_moment(str(package.get("action") or "")).split()).rstrip(". ")
    if moment and subject and moment.casefold() in subject.casefold():
        moment = ""  # the plan's action is its subject (a template plan): said once
    parts = [
        f"{subject[:1].upper()}{subject[1:]}." if subject else "",
        f"{moment[:1].upper()}{moment[1:]}." if moment else "",
    ]
    return " ".join(part for part in parts if part)


def _scene_picture(
    package: Mapping[str, Any], visual: str, words: str, *, serial: bool = False
) -> str:
    """The scene's written picture, for the gate's shows_scene. For a factual film the
    scriptwriter's line (``writer_visual``, kept on the package by the shot-prompt writer),
    else ``visual_prompt`` when it is not the still prompt itself, else nothing (the gate then
    judges by the plan, as its instructions say). For an episode of the serial, the beat as
    the composer draws it (`serial_scene_picture`), never the writer's line.

    2026-10-12, read on the database copy: ``visual_prompt`` equals the compiled still prompt
    on 1c038a99 scene 5, aa170155 scene 1 and f06808c9 scene 4 (`prompt_agent` stores what it
    composed there), so the «scene» the gate was shown was the plan again, and a prompt that
    had lost the scene's subject — the detector cavern of 1c038a99 scene 5, whose writer's
    line is «Return to the dark detector cavern from the opening shot…» — matched itself."""
    if serial or is_serial_package(package):
        return serial_scene_picture(package)
    # A shot the montage cut from the writer's scene shows one part of it at its size: its
    # picture is the shot's own (`factual_shot_picture`), never the whole scene's line.
    shot = factual_shot_picture(package) if montage_shot(package) is not None else ""
    if shot:
        return shot
    writer = " ".join(str(package.get("writer_visual") or "").split())
    if writer:
        return writer
    visual = " ".join(visual.split())
    return visual if visual != " ".join(words.split()) else ""


def _still_plan(scene: _Scene, *, faces_forbidden: bool, rules: tuple[str, ...]) -> StillPlan:
    """What the gate judges one candidate of ``scene`` against: its words, look and move, the
    bible, the scene itself (its written picture, narration and purpose) and what its words
    were rewritten to fix. The one place a still's plan is built, for every still bought or
    collected — the per-request path, the RunPod rounds and the scene redo — so none of them
    can leave the fix check out."""
    requirements: list[dict[str, str]] = []
    for match in re.finditer(
        r"Only the body parts specified for (.+?) enter the frame; the face stays outside it",
        scene.picture,
        re.IGNORECASE,
    ):
        name = match.group(1)
        requirements.append(
            {
                "finding": (
                    f"{name} is cropped to the specified body parts; "
                    f"no face, profile or head of {name} is visible."
                ),
                "expected": scene.picture,
                "layer": "still",
                "source": "current_plan",
                "source_id": f"partial:{name}",
                "cause": (
                    "Verify this explicit framing condition on the actual image, "
                    "not from the prompt. "
                    "A large visible face is not a minor trace."
                ),
            }
        )
    if re.search(r"\bunruled\b", scene.words, re.IGNORECASE):
        requirements.append(
            {
                "finding": (
                    "The pages are blank and unruled: "
                    "no ledger grid, printed lines, letters or numbers on the pages."
                ),
                "expected": (
                    "Smooth undecorated blank pages; preserve markings "
                    "on other objects explicitly named by the plan."
                ),
                "layer": "still",
                "source": "current_plan",
                "source_id": "unruled-pages",
                "cause": (
                    "A ruled grid contradicts the explicitly unruled pages "
                    "even when its text is too small to read."
                ),
            }
        )
    return StillPlan(
        scene=scene.index,
        still_prompt=scene.words,
        camera_move=scene.camera_move,
        faces_forbidden=faces_forbidden,
        bible_rules=rules,
        look_block=scene.look_block,
        palette_words=_palette_words(scene.look_block),
        scene_picture=scene.picture,
        narration=scene.narration,
        purpose=scene.purpose,
        must_fix=(*scene.must_fix, *requirements),
        expected_markings=scene.expected_markings,
        shot_form=scene.shot_form,
    )


def _read_scenes(engine: Engine, storyboard_id: str) -> tuple[dict[str, Any], list[_Scene]]:
    """The film's scenes as the step reads them: each LIVE scene's still identity (its words
    and the reference picture of the character it shows, the identity `assemble_from_takes`
    looks for), its approved still, what was bought and not settled, and what it remembers
    since the Owner last decided about it (`assembler.scene_memory`)."""
    from app.agents.editorial import is_serial_film  # noqa: PLC0415 - agents import media
    from app.factual.models import ScriptDraft  # noqa: PLC0415
    from app.media.prompt_agent import incomplete_plan_fields  # noqa: PLC0415
    from app.media.services import ReferenceRequired  # noqa: PLC0415 - services imports media

    loaded: dict[str, bytes] = {}
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise ValueError(f"Storyboard {storyboard_id} not found")
        bible = dict(board.visual_bible_json or {})
        script = session.get(ScriptDraft, board.script_draft_id) if board.script_draft_id else None
        # An episode of the office serial: its scenes' written picture is the composed beat.
        serial = bool(is_serial_film(board, script))
        rows = list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == storyboard_id)
                .order_by(StoryboardScene.scene_index)
            ).all()
        )
        if not rows:
            raise ValueError(f"Storyboard {storyboard_id} has no scenes")
        scenes: list[_Scene] = []
        for row in rows:
            package = dict(row.prompt_json or {})
            kind = scene_kind_of({"scene_kind": row.scene_kind})
            visual = str(row.visual_prompt or "")
            words = str(package.get("still_prompt") or visual) if kind == LIVE_KIND else ""
            # The take's identity is the scene's planned still (its words, the reference
            # picture of its character, and the model), the same identity
            # `assemble_from_takes` looks for. A re-roll's positive words and Figure 1 are how
            # this step reaches that still, not a different still.
            reference: dict[str, Any] | None = None
            missing: str | None = None
            if kind == LIVE_KIND:
                try:
                    reference = scene_reference(
                        engine, {"character_ids": list(row.character_ids_json or [])}, cache=loaded
                    )
                except ReferenceRequired as exc:
                    missing = str(exc)
            identity = still_fields(visual, reference)
            picture = _scene_picture(package, visual, words, serial=serial)
            marked = planned_markings(words, picture)
            scene = _Scene(
                index=int(row.scene_index),
                kind=kind,
                words=" ".join(words.split()),
                identity=identity,
                look_block=str(package.get("look_block") or ""),
                camera_move=str(package.get("camera_move") or ""),
                source=package.get("source") if isinstance(package.get("source"), str) else None,
                reference=reference,
                needs_reference=missing,
                negative=still_negative(package, bible, marked),
                picture=picture,
                narration=" ".join(str(row.voiceover_segment or "").split()),
                purpose=str(row.story_purpose or ""),
                expected_markings=marked,
                prompt_issues=tuple(incomplete_plan_fields(package, layers=("still",))),
                location=" ".join(str(package.get("location") or "").split()),
                shot_form=None if serial else montage_shot(package),
            )
            if kind == LIVE_KIND:
                # The picture's open items only: a finding treated in the motion's words is
                # the clip's to check (`assembler._clip_plan`), never answered by a still.
                scene.must_fix = tuple(
                    open_findings(session, storyboard_id, scene.index, layer=STILL_LAYER)
                )
            if kind == LIVE_KIND and missing is None:
                found = usable_take(
                    session, storyboard_id, scene.index, "still", [identity], statuses=("APPROVED",)
                )
                if found is not None:
                    session.expunge(found)
                    scene.reuse = found
                else:
                    scene.pending = _pending_takes(session, storyboard_id, scene)
                    # Only the stills that were made: a request that made nothing (unanswered,
                    # proven never queued, refused) is sent again on its own keys and seeds.
                    scene.rolls = int(
                        session.scalar(
                            select(func.count(SceneTake.id)).where(
                                SceneTake.storyboard_id == storyboard_id,
                                SceneTake.scene_number == scene.index,
                                SceneTake.kind == "still",
                                SceneTake.status.in_(_MADE_STILL_STATUSES),
                            )
                        )
                        or 0
                    )
            scenes.append(scene)
    # The Owner's renders cap (`renders_cap`) for a scene held after its rounds: its stills
    # made as many times as the cap allows, none approved, the rewrite ladder still turning —
    # the newest refused still is the scene's picture (approved under the cap) and nothing more
    # is bought for it (02:04Z, 87c05891 scene 1: the whole episode waited on a fourth). A
    # scene whose motion has had its renders buys no new picture either: no clip could be made
    # from it. One with nothing of its own left on disk to stand is not bought past the cap:
    # it waits, said so (2026-10-16: «maxim încă o randare»).
    # A scene whose last render is still pending (open at the vendor, or collected and not
    # judged) is left to it: its candidates are judged first (`_settle_pending`), and the round
    # applies the cap to them (`_settle_round`), so a paid render is never passed over for an
    # older refused still.
    capped: dict[int, str] = {}
    cap_now = renders_per_layer()
    for scene in scenes:
        if scene.kind != LIVE_KIND or scene.reuse is not None or scene.needs_reference:
            continue
        with Session(engine) as session:
            scene.renders = renders_made(session, storyboard_id, scene.index, "still")
            motion_full = renders_made(session, storyboard_id, scene.index, "motion") >= cap_now
        if scene.pending or (not motion_full and scene.renders < cap_now):
            continue
        kept = _keep_under_renders_cap(engine, storyboard_id, scene.index)
        if kept is None:
            with Session(engine) as session:
                his_no = _owner_rejected_still(session, storyboard_id, scene.index)
            capped[scene.index] = capped_reason(
                scene.index, motion=motion_full, owner_rejected=his_no
            )
            continue
        scene.reuse = kept
        scene.pending = []
    # What each scene still to be bought remembers since the Owner last decided about it: a
    # scene the gate or the vendor left to him is held, and is never bought meanwhile.
    open_scenes = {
        scene.index: scene
        for scene in scenes
        if scene.kind == LIVE_KIND and scene.reuse is None and scene.needs_reference is None
    }
    memory = scene_memory(
        engine,
        storyboard_id,
        "still",
        {index: scene.identity for index, scene in open_scenes.items()},
    )
    for index, scene in open_scenes.items():
        remembered = memory.get(index)
        if remembered is None:
            continue
        scene.attempts = remembered.attempts
        if not scene.pending:
            scene.hold_ro = remembered.hold_ro
    for index, reason in capped.items():
        held_scene = open_scenes.get(index)
        if held_scene is not None and not held_scene.hold_ro:
            held_scene.hold_ro = reason
    return bible, scenes


def capped_reason(scene_index: int, *, motion: bool = False, owner_rejected: bool = False) -> str:
    """Why a scene at the Owner's renders cap with nothing of its own on disk to stand is not
    bought: past the cap nothing is bought, by any route (his press included: «maxim încă o
    randare»); only his setting (STUDIO_RENDERS_PER_LAYER) moves the number. Paid renders
    that left no picture are the vendor's (charged and undelivered, or unanswered); a picture
    he rejected himself stands only if he chooses it again (``owner_rejected``)."""
    layer = "mișcării" if motion else "imaginii"
    left = (
        "imaginea ei rămasă pe disc a fost respinsă de Proprietar și rămâne doar dacă o alege "
        "din nou pe foaia de filmare"
        if owner_rejected
        else "nicio randare plătită nu a lăsat pe disc o imagine a ei care să rămână"
    )
    return (
        f"Scena {scene_index}: plafonul Proprietarului de {renders_of_ro(layer)} este "
        f"atins și {left}; nu se mai cumpără nimic pentru ea cât timp plafonul "
        "(STUDIO_RENDERS_PER_LAYER) rămâne acesta."
    )


def _pending_takes(session: Session, storyboard_id: str, scene: _Scene) -> list[SceneTake]:
    """The scene's still takes of its current identity that were bought and not settled."""
    rows = session.scalars(
        select(SceneTake)
        .where(
            SceneTake.storyboard_id == storyboard_id,
            SceneTake.scene_number == scene.index,
            SceneTake.kind == "still",
            SceneTake.status.in_(PENDING_STATUSES),
        )
        .order_by(SceneTake.created_at)
    ).all()
    pending: list[SceneTake] = []
    for row in rows:
        if take_hash(scene.identity, row.model_id) != row.prompt_hash:
            continue
        if row.status == "PAID" and row.failure_code != UNJUDGED_FAILURE_CODE:
            continue  # a judged runner-up the Owner may pick: settled
        session.expunge(row)
        pending.append(row)
    return pending


def stills_plan(
    engine: Engine,
    storyboard_id: str,
    *,
    model_id: str = STILLS_MODEL,
    table: PriceTable | None = None,
) -> dict[str, Any]:
    """The stills step as the Owner is shown it, with its plan_hash. 0 credits, no network.

    The hash covers what will be bought and how: each scene's kind and still prompt as sent,
    the model, the ratio, the candidates, the re-roll limit, the scenes reused from an
    approved take (by sha256) and the credits. Any change to these is a new plan, and a yes
    for the old one buys nothing.
    """
    prices = table or load_price_table()
    bible, scenes = _read_scenes(engine, storyboard_id)
    per_scene = price_still(model_id, STILLS_RESOLUTION, STILL_CANDIDATES, table=prices)
    row = prices.row(model_id, STILLS_RESOLUTION)
    every_live = [scene for scene in scenes if scene.kind == LIVE_KIND]
    live = [scene for scene in every_live if scene.reuse is None]
    # A scene with a request still open at the vendor, or candidates not judged yet, is not
    # bought: it is collected and judged first (0 credits).
    pending = [scene.index for scene in live if scene.pending]
    # A scene left to the Owner (the gate, a refusal, the attempt limit) is not bought until
    # he decides; nor is any scene of a film whose locked character has no reference picture.
    held = [scene.index for scene in live if scene.hold_ro and not scene.pending]
    needs_reference = [
        {"scene_index": scene.index, "reason_ro": scene.needs_reference}
        for scene in every_live
        if scene.needs_reference
    ]
    to_buy = [
        scene.index
        for scene in live
        if not scene.pending and not scene.hold_ro and not scene.needs_reference
    ]
    first = every_live[0] if every_live else None
    if needs_reference or (first is not None and first.index in held):
        # Scene 1 is Figure 1 for the film: while it waits for the Owner nothing later can be
        # bought, and a film that cannot draw a locked character is bought for no scene.
        to_buy = []
    cost = per_scene * len(to_buy)
    # Each scene's round, bought as many times as the Owner's renders cap still allows it
    # (`renders_cap`: the first render and its re-rolls, every render it already had counted):
    # the step never holds money for a render past the cap.
    by_index = {scene.index: scene for scene in live}
    cap_now = renders_per_layer()
    rerolls = cap_now - 1
    rounds = {
        index: max(1, min(1 + rerolls, cap_now - by_index[index].renders)) for index in to_buy
    }
    cap = per_scene * sum(rounds.values())
    # RunPod Serverless: every round is one batch job that pays a GPU start (cold start + idle
    # tail). Scene 1 goes first while the film has no Figure 1 when the later scenes can carry
    # it (a model that binds reference pictures; otherwise every scene is in round 1,
    # `_StillRounds`), so such a step is at most two series of rounds, and both are priced
    # whatever the model; the worst case is every re-roll round of each (0 for a per-image
    # vendor).
    overhead = prices.round_overhead("image", model_id)
    series = 2 if first is not None and first.index in to_buy and len(to_buy) > 1 else 1
    if to_buy and overhead:
        cost += overhead * series
        cap += overhead * series * max(rounds.values())
    planned = {
        "storyboard_id": storyboard_id,
        "step": STILLS_STEP,
        "model_id": model_id,
        "ratio": STILL_RATIO,
        "resolution": STILLS_RESOLUTION,
        "candidates": STILL_CANDIDATES,
        "max_rerolls": rerolls,
        "faces_forbidden": bible_face_rule(bible) is not None,
        "scenes": [
            {
                "scene_index": scene.index,
                "kind": scene.kind,
                "still_prompt": scene.words if scene.kind == LIVE_KIND else "",
                "reused_sha256": scene.reuse.sha256 if scene.reuse is not None else None,
                "reference_sha256": scene.identity.get("reference_sha256"),
                "status": _scene_status(scene, to_buy),
                "reason_ro": scene.needs_reference or scene.hold_ro or "",
            }
            for scene in scenes
        ],
        "to_buy": to_buy,
        "pending": pending,
        "held": held,
        "needs_reference": needs_reference,
        "credits_per_scene": per_scene,
        "cost_credits": cost,
        "cap_credits": cap,
    }
    if overhead:
        planned["round_overhead_credits"] = overhead
    plan_hash = hashlib.sha256(_canonical(planned).encode("utf-8")).hexdigest()
    return {
        **planned,
        "credit_usd": prices.credit_usd,
        "cost_usd": round(cost * prices.credit_usd, 6),
        "cap_usd": round(cap * prices.credit_usd, 6),
        "price_source": source_label(row),
        "plan_hash": plan_hash,
    }


def needs_reference_reason(missing: Sequence[dict[str, Any]]) -> str:
    """The Owner's words for a film whose locked character has no reference picture."""
    scenes = ", ".join(str(item["scene_index"]) for item in missing)
    first = str(missing[0].get("reason_ro") or "").strip() if missing else ""
    label = "Scena" if len(missing) == 1 else "Scenele"
    return (
        f"{label} {scenes}: {first} Nu se cumpără nicio imagine a filmului până nu există "
        "imaginea de referință: un chip blocat nu se desenează din cuvinte. Setul de "
        "referințe îl produce Proprietarul, din fișa personajului."
    ).strip()


def attempts_reason(scene: int, requests: int, limit: int) -> str:
    """Why a scene is bought no more: the paid attempt limit since the Owner's last word."""
    from app.wording import count  # noqa: PLC0415

    return (
        f"Scena {scene}: "
        + count(requests, "cerere plătită", "cereri plătite")
        + f" de imagini de la ultima decizie a Proprietarului, fără o imagine aprobată (limita "
        f"este {limit}); nu se mai cumpără nimic pentru ea până nu decide el pe foaia de "
        "filmare."
    )


def _scene_status(scene: _Scene, to_buy: list[int]) -> str:
    """One scene's line in the plan: what the step will do with it."""
    if scene.kind != LIVE_KIND:
        return "COMPOSED"
    if scene.reuse is not None:
        return "APPROVED"
    if scene.needs_reference:
        return "NEEDS_REFERENCE"
    if scene.pending:
        return "PENDING"
    if scene.hold_ro:
        return "NEEDS_OWNER"
    return "TO_BUY" if scene.index in to_buy else "WAITING"


# ----------------------------------------------------------------------------- helpers


def _palette_words(look_block: str) -> tuple[str, ...]:
    """The colour words the look names, longest first, without overlaps ('slate blue', not
    also 'blue')."""
    text = f" {look_block.lower()} "
    found: list[str] = []
    for word in sorted(COLOUR_WORDS, key=len, reverse=True):
        if word in text and not any(word in longer for longer in found):
            found.append(word)
    return tuple(found)


def _bible_rules(bible: dict[str, Any]) -> tuple[str, ...]:
    rules: list[str] = []
    for key in ("continuity_rules", "rules", "people_rule"):
        value = bible.get(key)
        if isinstance(value, str) and value.strip():
            rules.append(value.strip())
        elif isinstance(value, list | tuple):
            rules += [str(item).strip() for item in value if str(item).strip()]
    return tuple(dict.fromkeys(rules))


def _prompt(
    scene: _Scene, instruction: str, with_figure: bool, *, with_character: bool = False
) -> str:
    """The words sent for one request: the scene, what a re-roll asks for, and what each
    reference picture is for, in the order the pictures go (`_references`)."""
    parts = [scene.words]
    if instruction:
        parts.append(f"Show {instruction}.")
    if with_character and scene.reference is not None:
        name = str(scene.reference.get("canonical_name") or "the character")
        parts.append(CHARACTER_FIGURE.format(name=name))
    if with_figure:
        parts.append(FIGURE_TWO if with_character else FIGURE_ONE)
    return " ".join(part for part in parts if part)


def same_room(scene_location: str, figure_location: str) -> bool:
    """Whether a scene is in the room of the film's Figure 1. 2026-10-15 (episode 2,
    2d276038): the film's first still, Kael in the render bay, went with every later scene
    «for its light, palette and grain», and the edit model (Qwen-Image-Edit) drew its room
    — three monitors, the RGB tower, the lamps and the street window — behind Sarah in the
    penthouse and behind Dr. Aris in the research room, whatever the words said, through
    five paid rounds. A scene whose room is named and is not the figure's room is drawn
    from its character's reference and its words alone; a scene with no room named (a
    factual film) keeps the figure as before."""
    mine = " ".join(str(scene_location or "").casefold().split())
    theirs = " ".join(str(figure_location or "").casefold().split())
    return not mine or not theirs or mine == theirs


def _references(
    scene: _Scene,
    figure_one: bytes | None,
    adapter: Any,
    *,
    first: bool,
    figure_location: str = "",
) -> tuple[list[bytes], bool, bool]:
    """(the pictures sent with the scene's request, whether its character's reference is
    among them, whether the film's Figure 1 is). The character's reference goes first, for
    the face, the hair and the outfit; the film's first approved still second, for its light
    only. A vendor that does not say it takes a reference is not handed one
    (`factory.accepts_reference_image`)."""
    from app.media.factory import accepts_reference_image  # noqa: PLC0415 - factory reaches us

    pictures: list[bytes] = []
    with_character = False
    if scene.reference is not None and accepts_reference_image(adapter):
        data = scene.reference.get("bytes")
        if isinstance(data, bytes) and data:
            pictures.append(data)
            with_character = True
    with_figure = (
        figure_one is not None and not first and same_room(scene.location, figure_location)
    )
    if with_figure and figure_one is not None:
        pictures.append(figure_one)
    most = getattr(adapter, "MAX_REFERENCES", None)
    if isinstance(most, int) and not isinstance(most, bool) and 0 <= most < len(pictures):
        # A vendor that states how many pictures its model binds (RunPod, from the catalogue)
        # is handed no more: the character's first (its face), then the film's look. A model
        # that binds none gets none, so no still is reported as drawn from a picture.
        pictures = pictures[:most]
        kept_character = with_character and bool(pictures)
        with_figure = with_figure and len(pictures) == int(kept_character) + 1
        with_character = kept_character
    return pictures, with_character, with_figure


def references_sent(with_character: bool, with_figure: bool) -> list[str]:
    """What the model was really handed, in order: the record of a scene (2026-10-09)."""
    return [
        role for role, sent in (("character", with_character), ("figure_one", with_figure)) if sent
    ]


def _event(engine: Engine, event_type: str, storyboard_id: str, payload: dict, corr: str) -> None:
    from app.services import append_event  # noqa: PLC0415 - services imports media

    with Session(engine) as session, session.begin():
        append_event(session, event_type, "storyboard", storyboard_id, 1, payload, corr)


def _read_balance(adapter: Any) -> tuple[bool, float | None, str | None]:
    """(read, balance, problem). An adapter with no balance read is (False, None, None)."""
    reader = getattr(adapter, "credit_balance", None)
    if not callable(reader):
        return False, None, None
    try:
        balance = asyncio.run(reader())
    except Exception as exc:  # noqa: BLE001 - any failure to read stops the purchase
        return True, None, f"soldul Runway nu a putut fi citit ({exc})"
    if isinstance(balance, bool) or not isinstance(balance, int | float):
        return True, None, None
    return True, float(balance), None


def _hears_submits(method: Any) -> bool:
    """Whether a vendor method takes ``on_submitted`` (by name, or through ``**kwargs``)."""
    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        p.name == "on_submitted" or p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters
    )


def _buy(
    adapter: Any,
    prompt: str,
    references: list[bytes],
    count: int,
    on_submitted: Callable[[str], None] | None = None,
) -> tuple[list[Any], float | None]:
    """The candidates of one request and the vendor's price for it (None when unstated).

    ``on_submitted(task_id)`` is handed to a vendor that tells when it accepted a task, so
    the task is on the books before any poll."""
    generate = getattr(adapter, "generate_candidates", None)
    if callable(generate):
        heard: dict[str, Any] = {}
        if on_submitted is not None and _hears_submits(generate):
            heard["on_submitted"] = on_submitted
        results = asyncio.run(
            generate(prompt, ratio=STILL_RATIO, count=count, references=list(references), **heard)
        )
    else:
        # An image vendor without candidates: the same request, once per candidate.
        width, height = (int(part) for part in STILL_RATIO.split(":"))
        extra: dict[str, Any] = {}
        if references:
            extra["reference_image"] = {"bytes": references[0], "mime_type": "image/png"}
        results = [
            asyncio.run(adapter.generate_image(prompt, width=width, height=height, extra=extra))
            for _ in range(count)
        ]
    quoted = getattr(adapter, "last_estimated_credits", None)
    if isinstance(quoted, bool) or not isinstance(quoted, int | float):
        quoted = None
    return list(results), quoted


def _not_looked_at(reason: str) -> StillJudgement:
    return StillJudgement(
        status="NOT_RUN",
        verdict=None,
        detail_ro=f"nu a fost privită: {reason}",
        run_id=None,
        looked_by=None,
        image_width=None,
    )


def _judge_candidate(
    engine: Engine,
    registry: Any | None,
    path: Path,
    plan: StillPlan,
    correlation_id: str,
    *,
    environment: str,
    judge: Judge,
    face_counter: FaceCounter | None,
    measure: Sequence[str],
    ffmpeg_path: str | None,
) -> StillReport:
    """Local checks first; the vision model only sees a candidate they did not stop."""
    checks = local_checks(
        path,
        plan,
        environment=environment,
        ffmpeg_path=ffmpeg_path,
        face_counter=face_counter,
        measure=measure,
    )
    stopped = [check for check in checks if check.blocking]
    if stopped:
        judgement = _not_looked_at(
            "verificările locale au oprit-o deja (" + "; ".join(c.code for c in stopped) + ")"
        )
    else:
        judgement = judge(engine, registry, path, plan, correlation_id, ffmpeg_path=ffmpeg_path)
    return decide(path, plan, checks, judgement, environment=environment)


def _set_verdicts(
    engine: Engine,
    verdicts: list[tuple[str, StillReport]],
    chosen: StillReport | None,
) -> None:
    """APPROVED for the chosen candidate, PAID for a passing runner-up, REJECTED otherwise."""
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        for take_id, report in verdicts:
            row = session.get(SceneTake, take_id)
            if row is None:
                continue
            if row.failure_code == UNJUDGED_FAILURE_CODE:
                # Judged now: the "not judged yet" mark goes, whatever the verdict.
                row.failure_code = None
                row.failure_detail = None
            if chosen is not None and report is chosen:
                row.status = "APPROVED"
                row.approved_by = GATE_REVIEWER
            elif report.decision == "PASSED":
                row.status = "PAID"
            else:
                row.status = "REJECTED"
                row.failure_code = GATE_FAILURE_CODE
                row.failure_detail = ("; ".join(report.reasons_ro) or "respinsă")[:500]
            sync_take_quality(
                session,
                row,
                accepted=report.decision == "PASSED",
                reason="; ".join(report.reasons_ro),
            )


# ------------------------------------------- after a round: her look, the notes, the lessons
#
# 2026-10-12, the Owner: «trece imaginile picate de la QC pe la Directoare și să decidă dacă
# au picat corect sau nu și dacă trebuie refăcute», and «LLM-ul este pe abonament! NU COSTĂ
# BANI SĂ TRECEM PE LA EI! GENERAREA DE IMAGINI ȘI MIȘCĂRI COSTĂ!». A round the gate refused
# whole was bought again on the gate's word alone; now the Director looks first, for free, at
# every refused candidate the bible's hard limits did not stop, and a candidate her look lets
# stand is approved by her — nothing is bought for it. Her confirmation goes with the re-roll.


@dataclass
class _RoundEnd:
    """What one judged round of a scene leads to: a take approved (by the gate or by her
    look), another round on the same words with ``instruction``, or ``outcome``."""

    take_id: str | None = None
    report: StillReport | None = None
    approved_by: str = GATE_REVIEWER
    again: bool = False
    instruction: str = ""
    outcome: dict[str, Any] | None = None
    #: Her look, when hers approved the take; her reasons, when she confirmed the refusal.
    look: dict[str, Any] | None = None
    confirmed: list[str] = field(default_factory=list)
    #: She confirmed a refusal that says the WORDS ask for the wrong picture
    #: (`still_gate.content_refusal`): another seed on them is not bought.
    confirmed_content: bool = False

    def approved(self) -> dict[str, Any]:
        """The scene's outcome for the approved take, with what was accepted on it."""
        said: dict[str, Any] = {
            "status": "APPROVED",
            "take_id": self.take_id,
            "score": self.report.score if self.report is not None else 0.0,
        }
        if self.approved_by != GATE_REVIEWER:
            said["approved_by"] = self.approved_by
            said["director_look"] = fix_check.look_record(self.look)
        if self.report is not None and self.report.minor:
            said["minor_defects"] = [dict(item) for item in self.report.minor]
        return said


# The Owner's renders cap (2026-10-15: «Randările odată făcute, de maxim 3x pentru fiecare
# imagine sau mișcare … publicăm cu ce Directoarea alege ca fiind cel mai apropiat»; since
# 2026-10-16 two, `Settings.renders_per_layer`, read through `renders_cap`): past the cap's
# stills of a scene, the closest candidate stands as the scene's picture and the film goes on
# (01:46Z, 87c05891 scene 1: a third still refused by the gate, and scenes 2, 4, 6, 8 — which
# take their look from scene 1's picture — never bought).


def _at_renders_cap(engine: Engine, storyboard_id: str, scene_index: int) -> bool:
    """Whether the scene's still has had its renders already (every paid request among its
    takes, `assembler._paid_attempts`; the cap read now, `renders_cap.renders_per_layer`)."""
    with Session(engine) as session:
        return at_cap(session, storyboard_id, scene_index, "still")


def _motion_at_renders_cap(engine: Engine, storyboard_id: str, scene_index: int) -> bool:
    """Whether the scene's motion (its test shot and shots) has had its renders already."""
    with Session(engine) as session:
        return at_cap(session, storyboard_id, scene_index, "motion")


def _closest(verdicts: list[tuple[str, StillReport]]) -> tuple[str, StillReport]:
    """The refused candidate nearest the plan: fewest faults measured or unmeasured, then
    fewest reasons, then the best score."""
    return min(
        verdicts,
        key=lambda pair: (
            len(pair[1].violations) + len(pair[1].unmeasured),
            len(pair[1].reasons_ro),
            -pair[1].score,
        ),
    )


def _scene_stills(
    session: Session, storyboard_id: str, scene_index: int, status: str
) -> list[SceneTake]:
    """The scene's stills of ``status`` on disk, newest first, without those the Owner
    rejected himself (`assembler.owner_rejected_takes`): a picture he turned down is not used
    in a film unless he chooses it again, and the renders cap never approves it for him."""
    rows = list(
        session.scalars(
            select(SceneTake)
            .where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == int(scene_index),
                SceneTake.kind == "still",
                SceneTake.status == status,
            )
            .order_by(SceneTake.created_at.desc())
        )
    )
    his_no = owner_rejected_takes(session, rows)
    return [
        row
        for row in rows
        if row.id not in his_no and row.path and row.sha256 and Path(row.path).is_file()
    ]


def _newest_refused(session: Session, storyboard_id: str, scene_index: int) -> SceneTake | None:
    """The scene's newest still the gate refused that is still on disk: made on the most
    corrected words, the closest the scene has when the cap stops another render. Never one
    the Owner rejected himself (`_scene_stills`)."""
    rows = _scene_stills(session, storyboard_id, scene_index, "REJECTED")
    return rows[0] if rows else None


def _newest_kept(session: Session, storyboard_id: str, scene_index: int) -> SceneTake | None:
    """What stands as the scene's picture when the cap stops another render: its newest refused
    still on disk (`_newest_refused`), else its newest paid one on disk that was judged (a
    runner-up), else its newest still approved on other words that is on disk (the words were
    rewritten after it; no render of the new ones may be bought), else None. None of them is
    one the Owner rejected himself (`_scene_stills`)."""
    refused = _newest_refused(session, storyboard_id, scene_index)
    if refused is not None:
        return refused
    for status in ("PAID", "APPROVED"):
        for row in _scene_stills(session, storyboard_id, scene_index, status):
            if row.failure_code == UNJUDGED_FAILURE_CODE:
                continue
            return row
    return None


def _owner_rejected_still(session: Session, storyboard_id: str, scene_index: int) -> bool:
    """Whether the scene has a still on disk that the Owner rejected himself."""
    rows = [
        row
        for row in session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == int(scene_index),
                SceneTake.kind == "still",
            )
        )
        if row.path and Path(row.path).is_file()
    ]
    return bool(owner_rejected_takes(session, rows))


def _keep_under_renders_cap(
    engine: Engine, storyboard_id: str, scene_index: int
) -> SceneTake | None:
    """The scene's closest still (`_newest_kept`) APPROVED under the Owner's renders cap and
    returned, detached; None when nothing of it is on disk to stand."""
    with Session(engine) as session:
        newest = _newest_kept(session, storyboard_id, scene_index)
        take_id = newest.id if newest is not None else None
        said = str(newest.failure_detail or "") if newest is not None else ""
    if take_id is None:
        return None
    _approve_under_cap(engine, take_id, [said])
    with Session(engine) as session:
        kept = session.get(SceneTake, take_id)
        if kept is not None:
            session.expunge(kept)
        return kept


def _approve_under_cap(engine: Engine, take_id: str, reasons: list[str]) -> None:
    """The closest candidate APPROVED under the cap, its refusal cleared and kept as the
    lesson in its quality note."""
    left = "; ".join(dict.fromkeys(text for text in reasons if text))[:2500]
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        row = session.get(SceneTake, take_id)
        if row is None:
            return
        row.status = "APPROVED"
        row.approved_by = CAP_APPROVER
        row.failure_code = None
        row.failure_detail = None
        sync_take_quality(
            session,
            row,
            accepted=True,
            reason=(
                f"Acceptată sub plafonul Proprietarului ({renders_ro()}): cea mai apropiată "
                f"de plan; ce a rămas sub standard e lecție pentru filmul următor: {left}"
            )[:4000],
        )


#: A refused still judged again by the gate, free (`rejudge_refused_stills`).
REJUDGED_EVENT = "media.still_rejudged"
#: The gate's own words when its local checks stopped a still before any look at it.
LOCAL_STOP_MARK = "verificările locale au oprit-o"
#: How many of a scene's refused stills are judged again at one ladder stop.
MAX_REJUDGED = 2


def rejudge_refused_stills(
    engine: Engine,
    storyboard_id: str,
    scene_index: int,
    correlation_id: str,
    *,
    registry: Any | None = None,
    judge: Judge = judge_still,
    face_counter: FaceCounter | None = None,
    measure: Sequence[str] = ALL_CHECKS,
    ffmpeg_path: str | None = None,
) -> bool:
    """A scene's refused stills that the gate's LOCAL checks stopped before any look are
    judged again, by today's gate, when the scene has no approved still: 0 credits, no
    purchase. The gate reads differently after a fix (2026-10-16 05:04Z, the band rule:
    87c05891's desk fronts read as a pasted strip, then as a surface), but the refusal stood
    on the take, the Director's brief had pinned it to the composer's fixed sentences, and
    `scene_rewrite.scene_waits` stopped the ladder from asking her again — the episode could
    not start («Directoarea nu a putut încă rescrie scena 8», ×14). A still the gate now
    passes, local checks then the look, is APPROVED by the gate; one it refuses keeps its
    refusal in today's words. Returns True when a still was approved.

    Only a still made on the scene's CURRENT words and reference is judged again: one made on
    words the ladder has rewritten since can never be the scene's picture (`usable_take`
    reads the take's identity), so approving it moved nothing and the walk stopped at the
    same scene again. With no model registry nothing is judged and no take is touched: the
    look would answer «nu a fost privită», and that non-answer, written on the take, stripped
    the local-stop mark for good (the shooting-sheet letter called the ladder without the
    registry). A refusal the ladder had already sent to the Director's rewrite
    (`REWRITE_PHRASE`) stays hers when the gate refuses the still again, so the serial does
    not re-roll the same words; the take's job keeps its quality note, the verdict being the
    same."""
    from app.services import studio_environment, utc_now  # noqa: PLC0415 - it imports media

    if registry is None or not registry.registered_ids():
        return False
    bible, scenes = _read_scenes(engine, storyboard_id)
    scene = next((entry for entry in scenes if entry.index == int(scene_index)), None)
    if scene is None or scene.kind != LIVE_KIND or scene.reuse is not None:
        return False
    with Session(engine) as session:
        candidates = [
            (str(row.id), Path(str(row.path)))
            for row in session.scalars(
                select(SceneTake)
                .where(
                    SceneTake.storyboard_id == storyboard_id,
                    SceneTake.scene_number == int(scene_index),
                    SceneTake.kind == "still",
                    SceneTake.status == "REJECTED",
                    SceneTake.failure_code == GATE_FAILURE_CODE,
                )
                .order_by(SceneTake.created_at.desc())
            )
            if LOCAL_STOP_MARK in str(row.failure_detail or "")
            and take_hash(scene.identity, row.model_id) == row.prompt_hash
            and row.path
            and Path(str(row.path)).is_file()
        ][:MAX_REJUDGED]
    if not candidates:
        return False
    environment = studio_environment(engine)
    plan = _still_plan(
        scene, faces_forbidden=bible_face_rule(bible) is not None, rules=_bible_rules(bible)
    )
    for take_id, path in candidates:
        report = _judge_candidate(
            engine,
            registry,
            path,
            plan,
            correlation_id,
            environment=environment,
            judge=judge,
            face_counter=face_counter,
            measure=measure,
            ffmpeg_path=ffmpeg_path,
        )
        looked = report.judgement is not None and report.judgement.status == "MEASURED"
        if not looked and not any(check.blocking for check in report.checks):
            # Nobody judged it today (no model that sees, no 1080 px copy): the take keeps
            # its refusal and its mark, for a ladder stop that has eyes.
            continue
        _event(
            engine,
            REJUDGED_EVENT,
            storyboard_id,
            {
                "scene_index": int(scene_index),
                "take_id": take_id,
                "decision": report.decision,
                "reasons_ro": list(report.reasons_ro)[:6],
            },
            correlation_id,
        )
        if report.decision == "PASSED":
            _set_verdicts(engine, [(take_id, report)], report)
            with Session(engine) as session, session.begin():
                lock_for_write(session)
                row = session.get(SceneTake, take_id)
                if row is not None:
                    # The old refusal goes with the approval (`_set_verdicts` clears only
                    # the «not judged yet» mark).
                    row.failure_code = None
                    row.failure_detail = None
                    row.updated_at = utc_now()
            return True
        # Refused again, in today's words: the Director's next look reads today's reasons. A
        # refusal already sent to her rewrite keeps its content phrase first (`refusal_kind`
        # would read today's blur or panels as TECHNICAL and the serial would re-roll the words
        # her ladder holds back); the job's quality note is left, the verdict being the same.
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            row = session.get(SceneTake, take_id)
            if row is not None:
                today = "; ".join(report.reasons_ro) or "respinsă"
                was = " ".join(str(row.failure_detail or "").split())
                row.failure_detail = (
                    _rewrite_marked(today) if was.startswith(REWRITE_PHRASE) else today[:500]
                )
                row.updated_at = utc_now()
    return False


def settle_scene_under_cap(
    engine: Engine,
    storyboard_id: str,
    scene_index: int,
    correlation_id: str,
    *,
    act: bool = True,
) -> bool:
    """A stopped scene whose picture, or whose motion, has had its renders (`renders_cap`),
    whatever stopped it: what it has stands under the Owner's cap, before any rewrite, and
    nothing is bought or left to him (2026-10-15: «publicăm cu ce Directoarea alege ca fiind
    cel mai apropiat»; 2026-10-16: «maxim încă o randare»).

    Its picture: with no still approved for its words as they are now, its closest still on
    disk (`_newest_kept`: the newest refused, a judged runner-up, one approved on older words;
    never one the Owner rejected himself) is approved under the cap. A motion at its cap
    settles the picture whatever the picture's count: a new one could not be animated. Its
    motion, at its cap: the closest clip it has stands, else its still moved locally
    (`assembler.settle_motion_under_cap`). A render still pending (at the vendor, or collected
    and not judged) is judged first, never passed over. Returns True when something was
    settled (05:20Z, 7c26a7ce scenes 1-2: the still under the cap, three clips refused for it,
    and every walk stopped at «Directoarea nu a putut încă rescrie» — the ladder ran before
    the cap could act).

    ``act=False`` writes nothing and says whether it would settle something: only such a
    scene is said to be the Director's to settle under the cap (`runbook.stages._held_words`);
    one it cannot settle (a layer at the cap with nothing to keep, or a stop the cap did not
    make) is not."""
    from app.media.assembler import (  # noqa: PLC0415
        scene_approved_still,
        settle_motion_under_cap,
    )

    motion_full = _motion_at_renders_cap(engine, storyboard_id, scene_index)
    if not motion_full and not _at_renders_cap(engine, storyboard_id, scene_index):
        return False
    settled = False
    with Session(engine) as session:
        pending = session.scalar(
            select(SceneTake.id).where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == int(scene_index),
                SceneTake.kind == "still",
                (SceneTake.status == "SUBMITTED")
                | (
                    (SceneTake.status == "PAID") & (SceneTake.failure_code == UNJUDGED_FAILURE_CODE)
                ),
            )
        )
    if pending is None and scene_approved_still(engine, storyboard_id, scene_index) is None:
        if not act:
            with Session(engine) as session:
                if _newest_kept(session, storyboard_id, scene_index) is not None:
                    return True
        else:
            settled = _keep_under_renders_cap(engine, storyboard_id, scene_index) is not None
    if motion_full:
        moved = settle_motion_under_cap(engine, storyboard_id, scene_index, correlation_id, act=act)
        settled = moved or settled
    return settled


def _approve_by_look(engine: Engine, take_id: str, look: Mapping[str, Any]) -> None:
    """The candidate her look let stand, APPROVED by her (`fix_check.DIRECTOR_LOOK_APPROVER`),
    with no failure left on it — as `director_qc.record_look` writes her choice: a failure left
    on an approved still would hold the scene for the Owner's look, the wait hers replaces."""
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        row = session.get(SceneTake, take_id)
        if row is None:
            return
        row.status = "APPROVED"
        row.approved_by = fix_check.DIRECTOR_LOOK_APPROVER
        row.failure_code = None
        row.failure_detail = None
        sync_take_quality(
            session,
            row,
            accepted=True,
            reason=f"Aprobată de privirea Directoarei: {look.get('reason_ro') or ''}"[:4000],
        )


def _director_looks(
    engine: Engine,
    registry: Any | None,
    storyboard_id: str,
    scene: _Scene,
    verdicts: list[tuple[str, StillReport]],
    correlation_id: str,
) -> _RoundEnd:
    """Her second look at each candidate of a round the gate refused whole that she may
    overturn (`still_gate.may_be_overturned`), fewest violations first, one look per picture;
    the first her look lets stand (`fix_check.look_accepts`) is returned as approved. Free: a
    model call, no purchase. With nobody to ask she is UNAVAILABLE and the refusal stands."""
    offered = sorted(
        (pair for pair in verdicts if may_be_overturned(pair[1])),
        key=lambda pair: (len(pair[1].violations), len(pair[1].reasons_ro)),
    )
    confirmed: list[str] = []
    confirmed_content = False
    for take_id, report in offered:
        look = fix_check.director_second_look(
            engine,
            registry,
            storyboard_id=storyboard_id,
            scene_index=scene.index,
            kind="still",
            images=[report.path],
            refusal=list(report.reasons_ro),
            correlation_id=correlation_id,
            take_ids=[take_id],
        )
        # A floor the gate measured is kept only as «not in the picture» (defence in depth).
        if fix_check.look_accepts(look, measured=measured_refusal(report)):
            return _RoundEnd(
                take_id=take_id,
                report=report,
                approved_by=fix_check.DIRECTOR_LOOK_APPROVER,
                look=look,
                confirmed=confirmed,
                confirmed_content=confirmed_content,
            )
        if look.get("verdict") == fix_check.CONFIRMED:
            confirmed_content = confirmed_content or content_refusal(report)
            if look.get("reason_ro"):
                confirmed.append(str(look["reason_ro"]))
    return _RoundEnd(confirmed=confirmed, confirmed_content=confirmed_content)


def _after_approval(
    engine: Engine,
    storyboard_id: str,
    scene: _Scene,
    end: _RoundEnd,
    correlation_id: str,
) -> None:
    """What the approved take carries (`fix_check.record_take_note`: the minor traces and the
    review runs they belong to, her look) and what it teaches the rewrite's lessons, run by run
    (`fix_check.confirm_lessons`): a run is confirmed only when every one of its items this
    still answered is gone and none of its items is open on the clip's layer any more."""
    report = end.report
    if report is None or end.take_id is None:
        return
    with Session(engine) as session, session.begin():
        lock_for_write(session)  # reads the open items, then writes the note and the lessons
        fix_check.record_take_note(
            session,
            storyboard_id=storyboard_id,
            scene_number=scene.index,
            take_id=end.take_id,
            kind="still",
            approved_by=end.approved_by,
            minor=report.minor,
            look=end.look,
            correlation_id=correlation_id,
            answers=report.fixes,
        )
        if scene.must_fix:
            fix_check.confirm_lessons(
                session, report.fixes, storyboard_id=storyboard_id, scene_index=scene.index
            )


def _mark_for_rewrite(engine: Engine, verdicts: list[tuple[str, StillReport]]) -> None:
    """Every refused take of a round whose words go back to the Director's ladder begins with
    the content phrase (`still_gate.REWRITE_PHRASE`). 2026-10-12 (the review of 5fc7468,
    finding 3): the ladder reads the scene's NEWEST refused take (`scene_rewrite.serial_refusal`
    for the serial); a sibling refused for a blur read TECHNICAL and the serial re-rolled the
    very words her rewrite decision had sent back."""
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        for take_id, _report in verdicts:
            row = session.get(SceneTake, take_id)
            if row is None or row.status != "REJECTED":
                continue
            detail = " ".join(str(row.failure_detail or "").split())
            if detail.startswith(REWRITE_PHRASE):
                continue
            row.failure_detail = _rewrite_marked(detail)


def _rewrite_marked(detail: str) -> str:
    """A refused take's detail led by the content phrase (`still_gate.REWRITE_PHRASE`), within
    the take's 500 characters: the ladder reads it as a content refusal whatever follows."""
    detail = " ".join(str(detail or "").split())
    if detail.startswith(REWRITE_PHRASE):
        return detail[:500]
    return (
        f"{REWRITE_PHRASE}: runda nu se mai cumpără pe aceleași cuvinte, Directoarea "
        f"le rescrie; {detail or 'respinsă'}"
    )[:500]


def _settle_round(
    engine: Engine,
    registry: Any | None,
    storyboard_id: str,
    scene: _Scene,
    verdicts: list[tuple[str, StillReport]],
    correlation_id: str,
    *,
    rerolls: int,
) -> _RoundEnd:
    """One judged round of one scene, the same in the per-request path, the RunPod rounds and
    the paid still redo: the gate's best candidate APPROVED; else, before anything more is
    bought, her look at the refused ones; else the next step (`still_gate.round_step`). A
    proposed reroll goes to her brief/editor/review ladder before buying replacement words;
    a second look at the old image cannot approve the new prompt. The local compositor and
    unavailable measurements retain their own outcomes. No candidates: «nicio imagine»."""
    reports = [report for _take, report in verdicts]
    best = choose_best(reports)
    _set_verdicts(engine, verdicts, best)
    if best is not None:
        chosen = next(take for take, report in verdicts if report is best)
        end = _RoundEnd(take_id=chosen, report=best)
        _after_approval(engine, storyboard_id, scene, end, correlation_id)
        return end
    step = round_step(reports, rerolls_done=rerolls)
    if step is None:
        return _RoundEnd(
            outcome={
                "status": "NEEDS_OWNER",
                "reason": f"Scena {scene.index}: furnizorul nu a dat nicio imagine.",
            }
        )
    confirmed: list[str] = []
    if step.action in ("reroll", "rewrite", "needs_owner"):
        looked = _director_looks(engine, registry, storyboard_id, scene, verdicts, correlation_id)
        if looked.take_id is not None and looked.look is not None:
            _approve_by_look(engine, looked.take_id, looked.look)
            _after_approval(engine, storyboard_id, scene, looked, correlation_id)
            return looked
        confirmed = looked.confirmed
        if _at_renders_cap(engine, storyboard_id, scene.index):
            # The Owner's cap (`renders_cap`): its stills made, none passed, her look let none
            # stand — the closest candidate is the scene's picture and nothing more is bought.
            take_id, report = _closest(verdicts)
            _approve_under_cap(engine, take_id, [*report.reasons_ro, *confirmed])
            end = _RoundEnd(
                take_id=take_id, report=report, approved_by=CAP_APPROVER, confirmed=confirmed
            )
            _after_approval(engine, storyboard_id, scene, end, correlation_id)
            return end
        if step.action in ("reroll", "needs_owner") and any(
            report.violations for report in reports
        ):
            # Her second look concerns the old image, never the replacement prompt. Every
            # regeneration goes through the existing brief/editor/review ladder, including
            # technical faults, unavailable looks and hard limits she cannot overturn.
            step = rewrite_step(
                scene.index,
                "promptul de înlocuire trebuie verificat de Directoare pentru defectul "
                "constatat înainte de regenerare; o completare automată nu este o revizuire.",
            )
    if step.action == "rewrite":
        _mark_for_rewrite(engine, verdicts)
    if scene.must_fix and step.action != "reroll":
        # The words end here: a review run whose item a candidate showed again and none
        # corrected did not correct the mistake, and its lessons are withdrawn — run by run
        # (`fix_check.withdraw_lessons`). Not before a re-roll (a pair that also missed its
        # plan is drawn once more): a lesson withdrawn there could not be confirmed by the
        # re-roll that fixes it.
        with Session(engine) as session, session.begin():
            lock_for_write(session)  # the lessons are read before they are withdrawn
            fix_check.withdraw_lessons(session, [list(report.fixes) for report in reports])
    her_words = (
        " Directoarea a privit și confirmă refuzul: " + " | ".join(confirmed) if confirmed else ""
    )
    if step.action == "reroll":
        return _RoundEnd(
            again=True,
            instruction=positive_instruction(
                [code for report in reports for code in report.violations]
            ),
            confirmed=confirmed,
        )
    if step.action == "compose_locally":
        return _RoundEnd(outcome={"status": "COMPOSE_LOCALLY", "reason": step.reason_ro})
    outcome: dict[str, Any] = {
        "status": "NEEDS_OWNER",
        "reason": step.reason_ro + her_words,
        "reasons": list(dict.fromkeys(r for rep in reports for r in rep.reasons_ro)),
    }
    if step.action == "rewrite":
        # Not the Owner's to decide: her ladder rewrites the words (`scene_rewrite`), whose
        # rewrite releases the hold (`assembler.scene_memory`).
        outcome["rewrite"] = True
    if confirmed:
        outcome["director_confirmed"] = confirmed
    return _RoundEnd(outcome=outcome, confirmed=confirmed)


def _claim_intent(
    open_intents: list[tuple[str | None, str]], task_id: Any, every_task: list[str]
) -> tuple[str | None, str | None]:
    """The SUBMITTED take a delivered candidate lands on, and its task id.

    The candidate's own task when the vendor named it; else the first task still open; once
    each task has its first candidate, a further candidate (``outputCount`` > 1) gets a row
    of its own carrying the last task's id."""
    named = task_id if isinstance(task_id, str) and task_id else None
    for position, (_take, task) in enumerate(open_intents):
        if named is None or task == named:
            return open_intents.pop(position)
    return None, named or (every_task[-1] if every_task else None)


def _settle_pending(
    engine: Engine,
    registry: Any | None,
    storyboard_id: str,
    scene: _Scene,
    correlation_id: str,
    *,
    environment: str,
    judge: Judge,
    face_counter: FaceCounter | None,
    measure: Sequence[str],
    ffmpeg_path: str | None,
    faces_forbidden: bool,
    rules: tuple[str, ...],
) -> dict[str, Any]:
    """A scene this step does not buy: its unjudged candidates judged, or why it waits.

    Read again here, after the collection: a task collected this run has its candidates on
    disk now. Returns the scene's entry (``path`` is the approved still's, for Figure 1)."""
    with Session(engine) as session:
        current = _pending_takes(session, storyboard_id, scene)
    unjudged = [
        take
        for take in current
        if take.status == "PAID" and take.path and Path(str(take.path)).is_file()
    ]
    if unjudged:
        plan = _still_plan(scene, faces_forbidden=faces_forbidden, rules=rules)
        verdicts = [
            (
                take.id,
                _judge_candidate(
                    engine,
                    registry,
                    Path(str(take.path)),
                    plan,
                    correlation_id,
                    environment=environment,
                    judge=judge,
                    face_counter=face_counter,
                    measure=measure,
                    ffmpeg_path=ffmpeg_path,
                ),
            )
            for take in unjudged
        ]
        # Judged as every round is (`_settle_round`): the gate's best, else her look before the
        # scene is planned and bought again, else the next step — and a round whose words did
        # not correct the mistake goes back to her ladder, never planned again on them (the
        # review of 5fc7468, finding 12). Nothing is bought here: a re-roll is the sheet's.
        end = _settle_round(
            engine, registry, storyboard_id, scene, verdicts, correlation_id, rerolls=0
        )
        if end.report is not None:
            return {
                **end.approved(),
                "credits": 0,
                "judged_collected": len(verdicts),
                "path": str(end.report.path),
            }
        if end.outcome is not None and end.outcome.get("rewrite"):
            return {**end.outcome, "judged_collected": len(verdicts)}
        return {
            "status": "NOT_BOUGHT",
            "judged_collected": len(verdicts),
            "reason": f"Scena {scene.index}: imaginile ridicate de la furnizor au fost judecate "
            "și respinse; scena se planifică din nou pe foaia de filmare.",
        }
    if any(take.status == "SUBMITTED" for take in current):
        return {"status": "IN_FLIGHT", "reason": IN_FLIGHT_REASON.format(scene=scene.index)}
    return {
        "status": "NOT_BOUGHT",
        "reason": f"Scena {scene.index} nu este în planul aprobat al acestui pas; se planifică "
        "din nou pe foaia de filmare.",
    }


def settle_stills(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    *,
    image_adapter: Any,
    registry: Any | None = None,
    environment: str | None = None,
    judge: Judge = judge_still,
    face_counter: FaceCounter | None = None,
    measure: Sequence[str] = ALL_CHECKS,
    ffmpeg_path: str | None = None,
    storage_root: Path | None = None,
) -> dict[str, Any]:
    """What the stills step bought and left unsettled, settled without buying anything.

    A request the vendor delivered after its step ended is collected by its task id (a GET,
    free), and every PAID candidate never judged (collected late, or left by a process that
    died before its judgement) is judged by the gate (the local checks, then the vision model:
    tokens, no image). Nothing is bought and no yes is asked, so it runs even when the plan has
    nothing to buy: a film whose only open scene holds such candidates would otherwise never
    have a step that looks at them (2026-10-02, A7)."""
    from app.services import studio_environment  # noqa: PLC0415 - services imports media

    environment = environment or studio_environment(engine)
    collected: list[dict[str, Any]] = []
    if image_adapter is not None:
        collected = collect_submitted_takes(
            engine,
            collector_for=lambda _take: image_adapter,
            correlation_id=correlation_id,
            storyboard_id=storyboard_id,
            kinds=("still",),
            storage_root=storage_root,
        )
    # Her reading of an older brief's words before its candidates are checked (free).
    fix_check.read_film_reasons(
        engine, registry, storyboard_id=storyboard_id, correlation_id=correlation_id
    )
    bible, scenes = _read_scenes(engine, storyboard_id)
    results: list[dict[str, Any]] = []
    for scene in scenes:
        if scene.kind != LIVE_KIND or scene.reuse is not None or not scene.pending:
            continue
        if not any(take.status == "PAID" for take in scene.pending):
            continue  # a task still open at the vendor: nothing to judge yet
        settled = _settle_pending(
            engine,
            registry,
            storyboard_id,
            scene,
            correlation_id,
            environment=environment,
            judge=judge,
            face_counter=face_counter,
            measure=measure,
            ffmpeg_path=ffmpeg_path,
            faces_forbidden=bible_face_rule(bible) is not None,
            rules=_bible_rules(bible),
        )
        settled.pop("path", None)
        results.append({"scene_index": scene.index, **settled})
    summary = {"storyboard_id": storyboard_id, "collected": collected, "scenes": results}
    if collected or results:
        _event(engine, "media.stills_settled", storyboard_id, summary, correlation_id)
    return summary


# ------------------------------------------------------------------ RunPod rounds (batches)

#: Why a later scene waits on RunPod too: scene 1 gives the film its look (Figure 1).
FIGURE_ONE_MISSING = (
    "Scena {first} nu are încă o imagine aprobată; ea dă lumina, paleta și granulația "
    "filmului, așa că restul scenelor nu se cumpără fără ea."
)


@dataclass
class _SceneRound:
    """One scene bought in rounds: its words, its pictures and what its candidates did."""

    scene: _Scene
    entry: dict[str, Any]
    still_plan: StillPlan
    identity: str
    requests: int
    committed_before: float
    instruction: str = ""
    rerolls: int = 0
    retried: bool = False
    attempt: int = 1
    references: tuple[bytes, ...] = ()
    with_character: bool = False
    with_figure: bool = False
    outcome: dict[str, Any] | None = None
    #: This round's judged candidates (take id, report) and its failed items' codes.
    verdicts: list[tuple[str, StillReport]] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    uncertain: bool = False
    cancelled: bool = False
    intents: dict[str, str | None] = field(default_factory=dict)
    #: The REFUSED take of each item whose /run got no job id (journal row id -> take id).
    refused: dict[str, str] = field(default_factory=dict)
    #: Its /run was proven never queued (`gpu_batch.run_rounds`' proof): nothing was bought.
    not_queued: bool = False


#: Stands for the film's Figure 1 when asking whether a scene's request could carry it.
_ANY_FIGURE = b"figure"


@dataclass
class _StillRounds:
    """The stills step on RunPod Serverless: rounds of batches in one GPU session
    (`media.gpu_batch.run_rounds`), with the same gate, re-rolls and Figure 1 as the
    per-request path.

    Round 1 is every scene to buy: scenes left uncertain by an earlier /run and sent again with
    their keys, and every scene never sent. Only a scene whose request would really carry the
    film's Figure 1 (a model that binds reference pictures, the 2511 route) waits for scene 1's
    still; on a model that binds none (Qwen-Image-2512) Figure 1 is never sent, and waiting for
    it only starved the film: on 2026-10-09 scene 1 was re-rolled alone for three rounds and
    scenes 2-5 were never bought. Later rounds are what the gate sent back (re-rolls, one retry)
    and the scenes that waited for Figure 1; a cut keeps first candidates before re-rolls
    (`gpu_batch.fit_round`)."""

    engine: Engine
    storyboard_id: str
    correlation_id: str
    adapter: Any
    model_id: str
    first_live: int | None
    figure_one: bytes | None
    per_image: float
    overhead: float
    credit_usd: float
    ledger: _Ledger
    limit: int
    work_dir: Path
    environment: str
    registry: Any
    judge: Judge
    face_counter: FaceCounter | None
    measure: Sequence[str]
    ffmpeg_path: str | None
    faces_forbidden: bool
    rules: tuple[str, ...]
    states: dict[int, _SceneRound] = field(default_factory=dict)
    waiting: list[int] = field(default_factory=list)
    stop: str | None = None
    unverified: bool = False
    #: A one-scene still redo (`assembler._redo_still`): its hold event says so.
    redo: bool = False
    #: The room of the film's Figure 1 (scene 1's): the figure goes only to its own room.
    figure_location: str = ""

    # ------------------------------------------------------------------ requests

    def _prepare(self, state: _SceneRound) -> None:
        refs, with_character, with_figure = _references(
            state.scene,
            self.figure_one,
            self.adapter,
            first=state.scene.index == self.first_live,
            figure_location=self.figure_location,
        )
        state.references = tuple(refs)
        state.with_character, state.with_figure = with_character, with_figure
        state.entry["references_sent"] = references_sent(with_character, with_figure)
        self.unverified = self.unverified or (
            bool(refs) and not bool(getattr(self.adapter, "REFERENCE_IMAGE_VERIFIED", False))
        )

    def _carries_figure(self, scene: _Scene) -> bool:
        """Whether this scene's request would carry the film's Figure 1 once scene 1 has its
        still (`_references` with this adapter's reference limits): only such a scene waits."""
        _pictures, _character, with_figure = _references(
            scene, _ANY_FIGURE, self.adapter, first=False, figure_location=self.figure_location
        )
        return with_figure

    def _requests(self, state: _SceneRound) -> list[BatchRequest]:
        prompt = _prompt(
            state.scene, state.instruction, state.with_figure, with_character=state.with_character
        )
        width, height = (int(part) for part in STILL_RATIO.split(":"))
        return [
            BatchRequest(
                operation="image",
                project_id=self.storyboard_id,
                scene_id=str(state.scene.index),
                candidate_index=candidate,
                attempt_number=state.attempt,
                model=self.model_id,
                prompt=prompt,
                negative_prompt=state.scene.negative or None,
                # Seeded past every still the scene had before this step: a round bought
                # again on the same words (after the Director's decision) draws new pictures.
                seed=item_seed(
                    self.storyboard_id,
                    state.scene.index,
                    state.scene.rolls + state.attempt,
                    candidate,
                ),
                width=width,
                height=height,
                duration=None,
                fps=None,
                references=state.references,
                source_image=None,
                price_usd=Decimal(str(self.per_image)) * Decimal(str(self.credit_usd)),
            )
            for candidate in range(STILL_CANDIDATES)
        ]

    def price(self, requests: list[BatchRequest]) -> float:
        """A round's credits: its images and one GPU start (cold start + idle tail)."""
        return self.per_image * len(requests) + self.overhead

    def _send(self, state: _SceneRound) -> list[BatchRequest]:
        if state.requests >= self.limit:
            state.outcome = {
                "status": "NEEDS_OWNER",
                "reason": attempts_reason(state.scene.index, state.requests, self.limit),
            }
            return []
        from app.media.input_guard import (  # noqa: PLC0415
            REFUSAL_CODE,
            identity_of_request,
            record_refusal,
            refused_before,
        )

        requests = self._requests(state)
        identity = identity_of_request(requests[0])
        with Session(self.engine) as session, session.begin():
            refusal = refused_before(session, identity)
            if refusal is not None:
                record_refusal(session, identity, refusal, correlation_id=self.correlation_id)
        if refusal is not None:
            state.outcome = {
                "status": "NEEDS_OWNER",
                "failure_code": REFUSAL_CODE,
                "rewrite": refusal.layer is not None,
                "layer": refusal.layer,
                "reason": refusal.reason_ro,
            }
            return []
        state.requests += 1
        state.verdicts, state.failed = [], []
        return requests

    # ------------------------------------------------------------------ callbacks

    def submitted(self, item: SubmittedItem) -> None:
        """RunPod accepted the round: the candidate's take is SUBMITTED, before any poll."""
        state = self.states[int(item.request.scene_id)]
        state.intents[item.job_row_id] = _record_intent(
            self.engine,
            str(item.remote_item_id),
            storyboard_id=self.storyboard_id,
            scene_number=state.scene.index,
            kind="still",
            prompt_hash=state.identity,
            model_id=self.model_id,
            resolution=STILL_RATIO,
            correlation_id=self.correlation_id,
            credits=float(self.per_image),
            seed=item.request.seed,
        )

    def landed(self, outcome: ItemOutcome) -> None:
        """One candidate came back: kept as PAID and UNJUDGED, then judged at once (the worker
        meanwhile makes the next one)."""
        state = self.states[int(outcome.item.request.scene_id)]
        intent = state.intents.get(outcome.item.job_row_id)
        if outcome.state == "COMPLETED" and outcome.path is not None:
            content = Path(outcome.path).read_bytes()
            path = self.work_dir / (
                f"scene_{state.scene.index:02d}_{uuid4().hex[:8]}"
                f"_c{outcome.item.request.candidate_index + 1}.png"
            )
            path.write_bytes(content)
            self.ledger.images += 1
            take_id = record_take(
                self.engine,
                take_id=intent,
                storyboard_id=self.storyboard_id,
                scene_number=state.scene.index,
                kind="still",
                prompt_hash=state.identity,
                model_id=self.model_id,
                resolution=STILL_RATIO,
                status="PAID",
                correlation_id=self.correlation_id,
                credits_quoted=float(self.per_image),
                path=path,
                sha256=hashlib.sha256(content).hexdigest(),
                failure_code=UNJUDGED_FAILURE_CODE,
                failure_detail=UNJUDGED_DETAIL,
                remote_task_id=outcome.item.remote_item_id,
                seed=outcome.item.request.seed,
            )
            self.ledger.take_ids.append(take_id)
            report = _judge_candidate(
                self.engine,
                self.registry,
                path,
                state.still_plan,
                self.correlation_id,
                environment=self.environment,
                judge=self.judge,
                face_counter=self.face_counter,
                measure=self.measure,
                ffmpeg_path=self.ffmpeg_path,
            )
            state.verdicts.append((take_id, report))
            return
        error = str(outcome.error or outcome.state)
        uncertain = error == UNCERTAIN
        state.uncertain = state.uncertain or uncertain
        state.cancelled = state.cancelled or outcome.state == "CANCELLED"
        take_id = record_take(
            self.engine,
            take_id=intent,
            storyboard_id=self.storyboard_id,
            scene_number=state.scene.index,
            kind="still",
            prompt_hash=state.identity,
            model_id=self.model_id,
            resolution=STILL_RATIO,
            status="REFUSED",
            correlation_id=self.correlation_id,
            credits_quoted=float(self.per_image) if uncertain else None,
            failure_code=UNANSWERED_FAILURE_CODE if uncertain else f"RUNPOD.{error}"[:100],
            failure_detail=(
                "Nu s-a cumpărat: pasul s-a oprit înainte de această imagine."
                if outcome.state == "CANCELLED"
                else None
            ),
            remote_task_id=outcome.item.remote_item_id,
        )
        self.ledger.take_ids.append(take_id)
        if uncertain:
            state.refused[outcome.item.job_row_id] = take_id
        state.failed.append(error)

    def unsent(self, outcomes: list[ItemOutcome], proof: dict[str, Any]) -> None:
        """The GPU-off proved these items never queued (`gpu_batch.run_rounds`): their takes
        are re-recorded as not queued (no credits) and a scene whose every uncertain item was
        proven is no longer uncertain: nothing was bought, so nothing is held for the Owner."""
        touched: dict[int, _SceneRound] = {}
        for outcome in outcomes:
            state = self.states[int(outcome.item.request.scene_id)]
            take = state.refused.pop(outcome.item.job_row_id, None)
            if take is not None:
                with Session(self.engine) as session, session.begin():
                    lock_for_write(session)
                    recode_not_queued(
                        session,
                        [take],
                        detail=NOT_QUEUED_DETAIL,
                        correlation_id=self.correlation_id,
                        by="proof",
                    )
            touched[state.scene.index] = state
        for state in touched.values():
            if not state.refused:
                state.uncertain = False
                state.not_queued = True

    # ------------------------------------------------------------------- deciding

    def _decide(self, state: _SceneRound) -> str | None:
        """The scene after its round: APPROVED, an outcome for the Owner, or "again" (a
        re-roll, or one retry of items the worker failed)."""
        reports = [report for _take, report in state.verdicts]
        if choose_best(reports) is not None:
            return self._settled(state)
        if state.uncertain or state.cancelled or not reports:
            # A round stopped (no answer, cancelled) or empty buys nothing more here: its
            # candidates are refused as the gate said, without her look, which is for a
            # round that would otherwise be bought again.
            _set_verdicts(self.engine, state.verdicts, None)
        if state.uncertain:
            state.entry.update(failure_kind="UNANSWERED", failure_code=UNANSWERED_FAILURE_CODE)
            self.stop = UNANSWERED_REASON.format(scene=state.scene.index)
            state.outcome = {"status": "NEEDS_OWNER", "reason": self.stop}
            return None
        if state.not_queued and not reports:
            # RunPod never queued its /run (proven at the GPU-off): not bought, not held.
            state.outcome = {
                "status": "NOT_BOUGHT",
                "reason": NOT_QUEUED_REASON.format(scene=state.scene.index),
            }
            return None
        if state.cancelled:
            state.outcome = {
                "status": "NOT_BOUGHT",
                "reason": self.stop or "Pasul s-a oprit; restul nu s-a cumpărat.",
            }
            return None
        if not reports:
            if not state.retried:
                # The worker failed the items (not the gate): tried once more, same words.
                state.retried = True
                return "again"
            state.entry.update(failure_kind="BAD_OUTPUT", failure_code="; ".join(state.failed))
            state.outcome = {
                "status": "NEEDS_OWNER",
                "reason": f"Scena {state.scene.index}: RunPod nu a dat nicio imagine "
                f"({', '.join(dict.fromkeys(state.failed))}).",
            }
            return None
        return self._settled(state)

    def _settled(self, state: _SceneRound) -> str | None:
        """The round judged as every buyer judges one (`_settle_round`: the gate's best, else
        her look, else the next step)."""
        end = _settle_round(
            self.engine,
            self.registry,
            self.storyboard_id,
            state.scene,
            state.verdicts,
            self.correlation_id,
            rerolls=state.rerolls,
        )
        if end.report is not None:
            if state.scene.index == self.first_live:
                self.figure_one = Path(end.report.path).read_bytes()
            state.outcome = end.approved()
            return None
        if end.again:
            state.rerolls += 1
            state.instruction = end.instruction
            if end.confirmed:
                # Her confirmation goes with the re-roll it lets be bought.
                state.entry.setdefault("director_confirmed", []).extend(end.confirmed)
            return "again"
        state.outcome = dict(end.outcome or {})
        return None

    def next_round(self, outcomes: list[ItemOutcome]) -> list[BatchRequest]:
        """What the gate sent back, plus the rest of the film once scene 1 has its still."""
        touched = sorted({int(o.item.request.scene_id) for o in outcomes})
        again = [index for index in touched if self._decide(self.states[index]) == "again"]
        if self.stop is not None:
            return []
        requests: list[BatchRequest] = []
        for index in again:
            state = self.states[index]
            state.attempt += 1
            requests += self._send(state)
        if self.waiting and self.figure_one is not None:
            # Scene 1's still was approved in this round: the rest of the film has its look.
            for index in self.waiting:
                state = self.states[index]
                self._prepare(state)
                requests += self._send(state)
            self.waiting = []
        elif self.waiting and self.first_live is not None:
            first = self.states.get(self.first_live)
            if first is not None and first.outcome is not None:
                # Scene 1 ended without an approved still: nothing later is bought blind.
                for index in self.waiting:
                    self.states[index].outcome = {
                        "status": "NOT_BOUGHT",
                        "reason": FIGURE_ONE_MISSING.format(first=self.first_live),
                    }
                self.waiting = []
        return requests

    # ----------------------------------------------------------------------- run

    @purchase_flow
    def run(
        self,
        deferred: list[tuple[_Scene, dict[str, Any]]],
        *,
        permit: Any,
        guard: PurchaseGuard | None,
        stopped: Callable[[], str | None],
    ) -> Generator[RoundWork, dict[str, Any], dict[str, Any]]:
        from app.workflows.director_upkeep import director_wait_work  # noqa: PLC0415

        buying = {scene.index for scene, _entry in deferred}
        first: list[BatchRequest] = []
        for scene, entry in deferred:
            state = _SceneRound(
                scene=scene,
                entry=entry,
                still_plan=_still_plan(
                    scene, faces_forbidden=self.faces_forbidden, rules=self.rules
                ),
                identity=take_hash(scene.identity, self.model_id),
                requests=scene.attempts,
                committed_before=self.ledger.committed,
            )
            if scene.must_fix:
                # What each still of this scene is checked to have corrected (the register).
                entry["must_fix"] = [item["finding"] for item in scene.must_fix]
            self.states[scene.index] = state
            if (
                scene.index != self.first_live
                and self.figure_one is None
                and self._carries_figure(scene)
            ):
                if self.first_live in buying:
                    self.waiting.append(scene.index)  # bought once scene 1 has its still
                else:
                    state.outcome = {
                        "status": "NOT_BOUGHT",
                        "reason": FIGURE_ONE_MISSING.format(first=self.first_live),
                    }
                continue
            self._prepare(state)
            first += self._send(state)
        summary: dict[str, Any] = {"rounds": 0, "stopped": None, "cap_stop": None}
        if first:
            summary = yield RoundWork(
                engine=self.engine,
                adapter=self.adapter,
                permit=permit,
                purpose="image",
                first_round=first,
                next_round=self.next_round,
                price_credits=self.price,
                cap_left=self.ledger.room,
                # The budget hold grows to each round before it is fitted (`StepHold`).
                make_room=self.ledger.round_room if self.ledger.hold is not None else None,
                guard=guard,
                stopped=stopped,
                on_submitted=self.submitted,
                on_outcome=self.landed,
                meter=self.ledger.meter,
                credits_for_seconds=gpu_seconds_to_credits(
                    self.adapter, credit_usd=self.credit_usd
                ),
                on_unsent=self.unsent,
                on_wait=director_wait_work(self.engine, self.registry),
            )
        budget_cut(summary, self.ledger.budget_words)
        if summary.get("stopped") and summary.get("stopped") != UNCERTAIN:
            self.stop = self.stop or summary["stopped"]
        for index, state in self.states.items():
            if state.outcome is None and (state.verdicts or state.failed):
                self._decide(state)  # its last round, ended by a stop or the cap
            if state.outcome is None:
                state.outcome = {
                    "status": "NOT_BOUGHT",
                    "reason": self.stop
                    or summary.get("cap_stop")
                    or FIGURE_ONE_MISSING.format(first=self.first_live),
                }
            state.entry.update(state.outcome)
            state.entry["rerolls"] = state.rerolls
            if state.outcome["status"] in ("NEEDS_OWNER", "COMPOSE_LOCALLY"):
                free = (
                    str(state.entry.get("failure_kind") or "") in FREE_FAILURE_KINDS
                    and self.ledger.committed <= state.committed_before
                )
                _event(
                    self.engine,
                    STILL_HOLD_EVENT,
                    self.storyboard_id,
                    {
                        "severity": "WARNING",
                        "scene_number": index,
                        "status": state.outcome["status"],
                        "reason": state.outcome["reason"],
                        "rerolls": state.rerolls,
                        "failure_kind": state.entry.get("failure_kind"),
                        "identity": identity_key(state.scene.identity),
                        "holds": not free,
                        **({"redo": True} if self.redo else {}),
                        # Her ladder rewrites the words (the review of 5fc7468, finding 3).
                        **({"rewrite": True} if state.outcome.get("rewrite") else {}),
                        **runpod_hold_items(state.refused),
                    },
                    self.correlation_id,
                )
        summary["stopped"] = self.stop or summary.get("cap_stop")
        return summary


# ------------------------------------------------------------------------------ the step


def run_stills_stage(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    *,
    plan_hash: str,
    image_adapter: Any,
    registry: Any | None = None,
    environment: str | None = None,
    plan_hash_of: Callable[[Engine, str], str] | None = None,
    judge: Judge = judge_still,
    face_counter: FaceCounter | None = None,
    measure: Sequence[str] = ALL_CHECKS,
    ffmpeg_path: str | None = None,
    storage_root: Path | None = None,
    integration_id: str | None = None,
    table: PriceTable | None = None,
    requester: str = "video_editor",
    meter: SpendMeter | None = None,
    margin: float | None = None,
    unasked: bool = True,
    timezone: str | None = None,
    budget_hold: Any = None,
) -> dict[str, Any]:
    """The stills step of one film, bought only under the Owner's yes for this plan.

    ``margin`` is the Owner's balance margin (``settings.paid_step_balance_margin``; 1.15 by
    default): the step starts when the balance holds its first round x the margin, and buys
    each request only while the balance holds that request's price x the margin.

    ``unasked`` (the default) is a step nobody pressed: the day's staircase, FILM_CONTINUE. It
    is refused before the balance is read when the Policy Kernel refuses it outright, and before
    every request the kernel is asked again without spending anything (`mode_guard`): a mode he
    lowered, or a stricter rule, stops the step there (spec 51, «Lowering autonomy»). False is
    his own press on the sheet, which goes on through BLOCKED_MODE and NEEDS_APPROVAL
    (`media.services.OWNER_PRESS_PASSES`). ``timezone`` is his clock, for the stop's sentence.

    ``meter`` is kept up to date as requests are sent and credits committed, so the caller
    can book what was spent when the step raises half-way. A request that may have been
    charged without an answer (`assembler.possibly_charged`) is counted, never sent again
    automatically, and stops the step; before every request the balance is read again and
    the step stops when the account lost more than it counted.

    ``plan_hash`` is the hash of the plan the Owner was shown. By default the current plan is
    `stills_plan`; the shooting sheet may pass ``plan_hash_of`` so its own sheet hash is the
    one the yes is bound to. Raises `StillsStageRefused` when nothing may be bought; otherwise
    returns what was bought and judged, per scene.

    ``budget_hold`` is the sheet step's hold on the budgets (`shooting_sheet.StepHold`): it
    holds the step's first round, and is grown before every later purchase or round; what it
    cannot hold is not bought, and the step ends on the budget's words.
    """
    from app.economy.credits import record_measured_prices  # noqa: PLC0415
    from app.runbook.services import stop_requested  # noqa: PLC0415 - runbook imports media
    from app.services import may_act, studio_environment  # noqa: PLC0415

    if image_adapter is None:
        raise ValueError("the stills step needs an image adapter")
    prices = table or load_price_table()
    model_id = str(getattr(image_adapter, "model", None) or STILLS_MODEL)
    try:
        plan = stills_plan(engine, storyboard_id, model_id=model_id, table=prices)
    except UnpricedError as exc:
        # A still with no published price is never bought on a guess.
        raise StillsStageRefused("UNPRICED", f"Nu se cumpără imagini: {exc}.") from exc
    current = plan_hash_of(engine, storyboard_id) if plan_hash_of else plan["plan_hash"]
    if not plan_hash or plan_hash != current:
        raise StillsStageRefused(
            "STALE_PLAN",
            "Foaia de filmare s-a schimbat de când a fost aprobată (sau aprobarea numește alt "
            "plan): nu se cumpără nicio imagine. Deschideți foaia de filmare din nou și "
            "aprobați planul de acum.",
            plan=plan,
        )
    if plan["needs_reference"]:
        raise StillsStageRefused(
            "NEEDS_REFERENCE",
            needs_reference_reason(plan["needs_reference"]),
            plan=plan,
        )
    environment = environment or studio_environment(engine)
    # What the vendor already made for this film is collected (a GET each, nothing bought)
    # after his yes was matched to the plan he saw: collecting only takes scenes out of
    # buying, and his yes must not go stale because the vendor delivered.
    collected = collect_submitted_takes(
        engine,
        collector_for=lambda _take: image_adapter,
        correlation_id=correlation_id,
        storyboard_id=storyboard_id,
        kinds=("still",),
        storage_root=storage_root,
    )
    # What quality control SAW in an older brief's words, read by the Director (free), before
    # the stills are checked for it (`fix_check.read_film_reasons`; the review of 5fc7468,
    # finding 11: the patterns let process notes and her prescriptions through as sights).
    fix_check.read_film_reasons(
        engine, registry, storyboard_id=storyboard_id, correlation_id=correlation_id
    )
    bible, scenes = _read_scenes(engine, storyboard_id)
    live = [scene for scene in scenes if scene.kind == LIVE_KIND]
    to_buy = {int(index) for index in plan["to_buy"]}

    if environment == "PRODUCTION":
        # The model's shot plan; for an episode of the office serial also the scenes composed
        # from the Owner-approved series look (S8), which are linted and gated like any other.
        sources = shot_plan_sources(engine, storyboard_id)
        unwritten = [scene.index for scene in live if scene.source not in sources]
        if unwritten:
            raise StillsStageRefused(
                "NEEDS_SHOT_PLAN",
                "Scenele "
                + ", ".join(str(n) for n in unwritten)
                + " nu au promptul scris de model din planul de cadre; nu se cumpără imagini "
                "din prompturi-șablon.",
                plan=plan,
            )
    findings = lint_film(
        [
            LintScene(
                scene=scene.index,
                kind=scene.kind,
                still_prompt=scene.words,
                contract={"still_model_id": model_id},
                composition_issues=scene.prompt_issues if scene.index in to_buy else (),
            )
            for scene in scenes
        ],
        bible=bible,
    )
    if has_block(findings):
        blocks = [f for f in findings if f.severity == BLOCK]
        raise StillsStageRefused(
            "LINT_BLOCKED",
            summary_ro(findings) + " " + " ".join(f.message_ro for f in blocks[1:4]),
            findings=blocks,
            plan=plan,
        )

    from app.media.factory import accepts_reference_image  # noqa: PLC0415 - factory reaches us

    locked = [
        scene.index
        for scene in live
        if scene.index in to_buy
        and scene.reference is not None
        and scene.reference.get("required")
        and not accepts_reference_image(image_adapter)
    ]
    if locked:
        raise StillsStageRefused(
            "NEEDS_REFERENCE",
            "Scenele "
            + ", ".join(map(str, locked))
            + " arată un personaj cu înfățișarea blocată, iar modelul de imagine conectat nu "
            "poate primi imaginea lui de referință: nu se cumpără imagini desenate din cuvinte "
            "pentru un chip fixat. Alegeți un model care primește imagini de referință.",
            plan=plan,
        )
    if plan["to_buy"]:
        # A disk too full for the candidates refuses before anything is asked or bought
        # (REL-08): a still that cannot be written is a still paid for and lost.
        no_room = disk_refusal(storage_root or DEFAULT_STORAGE_ROOT)
        if no_room:
            raise StillsStageRefused(LOW_DISK, no_room, plan=plan)
    cap = int(plan["cap_credits"])
    margin = float(margin or BALANCE_MARGIN)
    asked_about = {"plan_hash": plan_hash, "cap_credits": cap}
    if plan["to_buy"] and supports_batch(image_adapter):
        # RunPod Serverless: a GPU that could not be switched on (his card not accepted, no
        # bucket) refuses here, before his yes is asked for or spent with nothing bought.
        from app.media import gpu_batch  # noqa: PLC0415 - gpu_batch reads runpod
        from app.providers.runpod.gpu_session import GpuSessionRefused  # noqa: PLC0415

        try:
            gpu_batch.gpu_precheck(
                engine, image_adapter, purpose="image", integration_id=integration_id
            )
        except GpuSessionRefused as exc:
            raise StillsStageRefused(str(exc.code), exc.reason_ro, plan=plan) from exc
    if plan["to_buy"] and unasked:
        # Unasked, the Owner's mode is asked before his balance (2026-10-04): a step the kernel
        # refuses outright reads no balance and raises no low-balance card.
        refused = unasked_refusal(
            engine,
            STILLS_ACTION,
            subject=storyboard_id,
            context=asked_about,
            cost_usd=plan["cap_usd"],
            requester=requester,
        )
        if refused is not None:
            raise StillsStageRefused(str(refused["status"]), str(refused["reason"]), plan=plan)
    read, before, problem = _read_balance(image_adapter) if plan["to_buy"] else (False, None, None)
    if problem is not None:
        raise StillsStageRefused(LOW_BALANCE, f"Nu se cumpără imagini: {problem}.", plan=plan)
    # The Owner's rule (2026-10-03): the step starts on its first round x the margin; the cap
    # stays the ceiling, read inside the loop, and every later request reads the balance again.
    first_round = int(plan["cost_credits"])
    if before is not None and before < needed_credits(first_round, margin):
        raise StillsStageRefused(
            LOW_BALANCE,
            start_refusal_ro(before, first_round, cap, margin, "pasului de imagini"),
            plan=plan,
        )

    if plan["to_buy"]:
        with Session(engine) as session, session.begin():
            verdict = may_act(
                session,
                STILLS_ACTION,
                requester=requester,
                subject=storyboard_id,
                evidence=(
                    f"{len(plan['to_buy'])} scene × {STILL_CANDIDATES} imagini la 2K, cost "
                    f"estimat {_usd_ro(plan['cost_usd'])}, plafon {_usd_ro(plan['cap_usd'])} "
                    "(cu reluările)"
                ),
                # The cap, the most his yes lets the step spend with its re-rolls (MONEY-08):
                # OVER_USD compares his threshold with it, not with the expected cost.
                cost_usd=plan["cap_usd"],
                context=asked_about,
            )
        if not verdict["allowed"]:
            raise StillsStageRefused(
                str(verdict["status"]),
                str(verdict["reason"]),
                approval_id=verdict.get("approval_id"),
                plan=plan,
            )
        # The same question again before every request, never spending (spec 51).
        guard: PurchaseGuard | None = PurchaseGuard.after(
            engine,
            verdict,
            action=STILLS_ACTION,
            step="stills",
            storyboard_id=storyboard_id,
            requester=requester,
            cost_usd=plan["cap_usd"],
            context=asked_about,
            unasked=unasked,
            correlation_id=correlation_id,
            timezone=timezone,
        )
    else:
        guard = None

    faces_forbidden = bible_face_rule(bible) is not None
    rules = _bible_rules(bible)
    per_request = int(plan["credits_per_scene"])
    per_image = per_request / STILL_CANDIDATES
    work_dir = (storage_root or DEFAULT_STORAGE_ROOT) / storyboard_id / "stills"
    work_dir.mkdir(parents=True, exist_ok=True)
    ledger = _Ledger(cap=cap, meter=meter if meter is not None else SpendMeter(), hold=budget_hold)
    limit = max_paid_attempts_per_scene()
    figure_one: bytes | None = None
    first_live = live[0].index if live else None
    figure_location = live[0].location if live else ""
    results: list[dict[str, Any]] = []
    stopped: str | None = None
    previous_kind: str | None = None
    unverified = False
    # Where the balance stopped the step, if it did (`balance_rule.low_balance_record`).
    low_balance: dict[str, Any] | None = None
    # RunPod Serverless buys in rounds of batches inside one GPU session (`gpu_batch`): the
    # scenes to buy are gathered here and bought after the loop, all at once.
    batching = bool(plan["to_buy"]) and supports_batch(image_adapter)
    deferred: list[tuple[_Scene, dict[str, Any]]] = []

    for scene in scenes:
        entry: dict[str, Any] = {"scene_index": scene.index, "scene_kind": scene.kind}
        results.append(entry)
        if scene.kind != LIVE_KIND:
            entry.update(status="composed", provenance="composed", credits=0)
            continue
        if scene.reuse is not None:
            entry.update(status="APPROVED", reused=True, take_id=scene.reuse.id, credits=0)
            if scene.index == first_live and scene.reuse.path:
                figure_one = Path(scene.reuse.path).read_bytes()
            continue
        if scene.hold_ro and not scene.pending:
            # Left to the Owner by an earlier step (the gate, a refusal, the attempt limit):
            # nothing is bought for it until he decides on the sheet.
            entry.update(status="NEEDS_OWNER", reason=scene.hold_ro, held=True, credits=0)
            continue
        if scene.pending or scene.index not in to_buy:
            # Bought before and not settled, or out of this plan's purchase: nothing is bought
            # for it here. Its collected candidates are judged (0 credits).
            settled = _settle_pending(
                engine,
                registry,
                storyboard_id,
                scene,
                correlation_id,
                environment=environment,
                judge=judge,
                face_counter=face_counter,
                measure=measure,
                ffmpeg_path=ffmpeg_path,
                faces_forbidden=bible_face_rule(bible) is not None,
                rules=_bible_rules(bible),
            )
            entry.update(settled)
            if settled["status"] == "APPROVED" and scene.index == first_live:
                figure_one = Path(str(settled["path"])).read_bytes()
            entry.pop("path", None)
            continue
        if stopped is not None:
            entry.update(status="NOT_BOUGHT", reason=stopped)
            continue
        if batching:
            deferred.append((scene, entry))
            continue
        if scene.index != first_live and figure_one is None:
            entry.update(
                status="NOT_BOUGHT",
                reason=f"Scena {first_live} nu are încă o imagine aprobată; ea dă lumina, "
                "paleta și granulația filmului, așa că restul scenelor nu se cumpără fără ea.",
            )
            continue
        still_plan = _still_plan(scene, faces_forbidden=faces_forbidden, rules=rules)
        if scene.must_fix:
            # What each still of this scene is checked to have corrected (the register).
            entry["must_fix"] = [item["finding"] for item in scene.must_fix]
        references, with_character, with_figure = _references(
            scene,
            figure_one,
            image_adapter,
            first=scene.index == first_live,
            figure_location=figure_location,
        )
        entry["references_sent"] = references_sent(with_character, with_figure)
        instruction = ""
        rerolls = 0
        retried = False
        outcome: dict[str, Any] | None = None
        # The scene's paid requests since the Owner last decided about it, this step's
        # included, and what was committed before it: read by the limit and by its event.
        requests = scene.attempts
        committed_before_scene = ledger.committed
        while outcome is None:
            if stop_requested(engine):
                stopped = "Proprietarul a oprit autonomia; nu se mai cumpără imagini."
                outcome = {"status": "NOT_BOUGHT", "reason": stopped}
                break
            lowered = guard.stop_reason(scene.index) if guard is not None else None
            if lowered is not None:
                # His mode or rule changed while the step ran: nothing more is bought.
                stopped = lowered
                outcome = {"status": "NOT_BOUGHT", "reason": stopped}
                break
            if _at_renders_cap(engine, storyboard_id, scene.index):
                # The Owner's renders cap, counted again before every request (2026-10-16:
                # «maxim încă o randare»): a charged vendor failure is a render too, so the
                # technical retry after one is not bought past the cap. What the scene has
                # stands under it (its closest still on disk), else nothing more is bought.
                kept = _keep_under_renders_cap(engine, storyboard_id, scene.index)
                if kept is None:
                    with Session(engine) as session:
                        his_no = _owner_rejected_still(session, storyboard_id, scene.index)
                    outcome = {
                        "status": "NOT_BOUGHT",
                        "reason": capped_reason(scene.index, owner_rejected=his_no),
                    }
                    break
                if scene.index == first_live and kept.path:
                    figure_one = Path(kept.path).read_bytes()
                outcome = _RoundEnd(take_id=kept.id, approved_by=CAP_APPROVER).approved()
                break
            if requests >= limit:
                outcome = {
                    "status": "NEEDS_OWNER",
                    "reason": attempts_reason(scene.index, requests, limit),
                }
                break
            if per_request > ledger.room(per_request) + 1e-9:
                stopped = ledger.budget_words(per_request) or (
                    f"STOPPED_AT_CAP: încă o cerere ({per_request} credite) ar depăși plafonul "
                    f"aprobat de {ledger.cap} credite (deja {ledger.committed:.0f})."
                )
                outcome = {"status": "NOT_BOUGHT", "reason": stopped}
                break
            _read, balance, problem = _read_balance(image_adapter)
            if problem is not None:
                stopped = f"Nu se mai cumpără imagini: {problem}."
                outcome = {"status": "NOT_BOUGHT", "reason": stopped}
                break
            if balance is not None and balance < needed_credits(per_request, margin):
                # The Owner's rule (2026-10-03): this request is not bought on a balance that
                # cannot hold it with the margin. The scene waits for his top-up; what it
                # bought is kept and nothing more is bought in this step.
                what = "reluarea imaginilor" if rerolls or retried else "o nouă cerere de imagini"
                stopped = purchase_stop_ro(scene.index, balance, per_request, margin, what)
                low_balance = low_balance_record(scene.index, balance, per_request, margin, stopped)
                entry["failure_kind"] = LOW_BALANCE
                outcome = {"status": "NEEDS_OWNER", "reason": stopped}
                break
            drop = uncounted_drop(before, balance, ledger.committed)
            if drop is not None:
                stopped = UNCOUNTED_DROP_STOP.format(drop=drop, committed=ledger.committed)
                outcome = {"status": "NOT_BOUGHT", "reason": stopped}
                break
            prompt = _prompt(scene, instruction, with_figure, with_character=with_character)
            identity = take_hash(scene.identity, model_id)
            # (take id, task id) of each task the vendor accepted for this request.
            intents: list[tuple[str | None, str]] = []

            def submitted(
                task_id: str,
                *,
                _scene: int = scene.index,
                _identity: str = identity,
                _intents: list[tuple[str | None, str]] = intents,
            ) -> None:
                _intents.append(
                    (
                        _record_intent(
                            engine,
                            task_id,
                            storyboard_id=storyboard_id,
                            scene_number=_scene,
                            kind="still",
                            prompt_hash=_identity,
                            model_id=model_id,
                            resolution=STILL_RATIO,
                            correlation_id=correlation_id,
                            credits=float(per_request),
                        ),
                        task_id,
                    )
                )

            ledger.meter.attempts += 1
            requests += 1
            try:
                bind_scene(image_adapter, storyboard_id, scene.index, "image")
                candidates, quoted = _buy(
                    image_adapter, prompt, references, STILL_CANDIDATES, on_submitted=submitted
                )
            except TaskStillOpen:
                # Accepted (and charged) and not delivered: the takes stay SUBMITTED with
                # their task ids, collected later; nothing more is bought in this step.
                ledger.committed += per_request
                ledger.take_ids += [take for take, _task in intents if take]
                stopped = IN_FLIGHT_STOP.format(scene=scene.index)
                outcome = {
                    "status": "IN_FLIGHT",
                    "reason": IN_FLIGHT_REASON.format(scene=scene.index),
                    "take_ids": [take for take, _task in intents if take],
                }
                break
            except MediaProviderError as exc:
                failure = classify_vendor_failure(exc, previous_kind)
                previous_kind = failure.kind
                charged = possibly_charged(exc, submitted=bool(intents))
                # No task heard and no answer (a vendor that names its failure code has
                # answered): it may have been served. Counted, and never sent again
                # automatically (MONEY-01).
                unknown = outcome_unknown(exc, submitted=bool(intents))
                if charged:
                    ledger.committed += per_request  # a refusal may be paid like a success
                for intent_take, _task in intents or [(None, "")]:
                    ledger.take_ids.append(
                        record_take(
                            engine,
                            take_id=intent_take,
                            storyboard_id=storyboard_id,
                            scene_number=scene.index,
                            kind="still",
                            prompt_hash=identity,
                            model_id=model_id,
                            resolution=STILL_RATIO,
                            status="REFUSED",
                            correlation_id=correlation_id,
                            credits_quoted=float(per_request) if charged else None,
                            failure_code=failure_code_of(exc)
                            or (UNANSWERED_FAILURE_CODE if unknown else None),
                            failure_detail=failure_detail_of(exc),
                        )
                    )
                if unknown:
                    entry.update(failure_kind="UNANSWERED", failure_code=failure_code_of(exc))
                    stopped = UNANSWERED_REASON.format(scene=scene.index)
                    outcome = {"status": "NEEDS_OWNER", "reason": stopped}
                    break
                if failure.kind in RETRY_KINDS and not retried:
                    retried = True
                    continue
                entry.update(failure_kind=failure.kind, failure_code=failure_code_of(exc))
                if failure.kind == STUDIO_DEFECT_KIND:
                    # Our request was wrong (the vendor names the parameter, 2026-10-04): the
                    # scene is not held for the Owner and nothing more is sent in this step.
                    stopped = f"Scena {scene.index}: {failure.reason_ro}"
                    outcome = {"status": "NOT_BOUGHT", "reason": stopped}
                    break
                if failure.stop_step:
                    stopped = failure.reason_ro
                outcome = {
                    "status": "NEEDS_OWNER",
                    "reason": f"Scena {scene.index}: {failure.reason_ro} Decide Proprietarul "
                    "pe foaia de filmare; aceleași cuvinte nu se trimit din nou.",
                }
                break
            previous_kind = None
            ledger.committed += max(float(per_request), float(quoted or 0))
            ledger.hold_spent()
            unverified = unverified or (
                bool(references)
                and not bool(getattr(image_adapter, "REFERENCE_IMAGE_VERIFIED", False))
            )
            share = (quoted / len(candidates)) if quoted and candidates else per_image
            verdicts: list[tuple[str, StillReport]] = []
            open_intents = list(intents)
            for number, candidate in enumerate(candidates):
                suffix = candidate.format if candidate.format in ("png", "jpeg", "webp") else "png"
                path = work_dir / (
                    f"scene_{scene.index:02d}_{uuid4().hex[:8]}_c{number + 1}."
                    + ("jpg" if suffix == "jpeg" else suffix)
                )
                path.write_bytes(candidate.image_bytes)
                ledger.images += 1
                raw = candidate.raw_response if isinstance(candidate.raw_response, dict) else {}
                intent_take, task_id = _claim_intent(
                    open_intents, raw.get("task_id"), [task for _take, task in intents]
                )
                # PAID and UNJUDGED until the gate below has looked: a process that dies in
                # between leaves a candidate the next step judges instead of buying again.
                take_id = record_take(
                    engine,
                    take_id=intent_take,
                    storyboard_id=storyboard_id,
                    scene_number=scene.index,
                    kind="still",
                    prompt_hash=identity,
                    model_id=model_id,
                    resolution=STILL_RATIO,
                    status="PAID",
                    correlation_id=correlation_id,
                    credits_quoted=float(share),
                    path=path,
                    sha256=hashlib.sha256(candidate.image_bytes).hexdigest(),
                    failure_code=UNJUDGED_FAILURE_CODE,
                    failure_detail=UNJUDGED_DETAIL,
                    remote_task_id=task_id,
                )
                ledger.take_ids.append(take_id)
                report = _judge_candidate(
                    engine,
                    registry,
                    path,
                    still_plan,
                    correlation_id,
                    environment=environment,
                    judge=judge,
                    face_counter=face_counter,
                    measure=measure,
                    ffmpeg_path=ffmpeg_path,
                )
                verdicts.append((take_id, report))
            for intent_take, _task in open_intents:
                # A task the vendor accepted that handed over nothing: refused, on its own row.
                if intent_take:
                    record_take(
                        engine,
                        take_id=intent_take,
                        storyboard_id=storyboard_id,
                        scene_number=scene.index,
                        kind="still",
                        prompt_hash=identity,
                        model_id=model_id,
                        resolution=STILL_RATIO,
                        status="REFUSED",
                        correlation_id=correlation_id,
                        failure_code=NO_OUTPUT_CODE,
                        failure_detail="Furnizorul a încheiat sarcina fără nicio imagine.",
                    )
            end = _settle_round(
                engine,
                registry,
                storyboard_id,
                scene,
                verdicts,
                correlation_id,
                rerolls=rerolls,
            )
            if end.report is not None:
                if scene.index == first_live:
                    figure_one = Path(end.report.path).read_bytes()
                outcome = end.approved()
                break
            if end.again:
                rerolls += 1
                instruction = end.instruction
                if end.confirmed:
                    # Her confirmation goes with the re-roll it lets be bought.
                    entry.setdefault("director_confirmed", []).extend(end.confirmed)
                continue
            outcome = dict(end.outcome or {})
        entry.update(outcome)
        entry["rerolls"] = rerolls
        if outcome["status"] in ("NEEDS_OWNER", "COMPOSE_LOCALLY"):
            # Whether the scene is held for the Owner (assembler.scene_memory): yes, unless
            # what went wrong cost nothing and was the vendor's or the account's.
            # A scene the balance stopped is never held: his top-up is the decision.
            free = entry.get("failure_kind") == LOW_BALANCE or (
                str(entry.get("failure_kind") or "") in FREE_FAILURE_KINDS
                and ledger.committed <= committed_before_scene
            )
            _event(
                engine,
                STILL_HOLD_EVENT,
                storyboard_id,
                {
                    "severity": "WARNING",
                    "scene_number": scene.index,
                    "status": outcome["status"],
                    "reason": outcome["reason"],
                    "rerolls": rerolls,
                    "failure_kind": entry.get("failure_kind"),
                    "identity": identity_key(scene.identity),
                    "holds": not free,
                    # Her ladder rewrites the words (the review of 5fc7468, finding 3).
                    **({"rewrite": True} if outcome.get("rewrite") else {}),
                },
                correlation_id,
            )

    gpu: dict[str, Any] | None = None
    if deferred:
        from app.providers.runpod.gpu_session import StepPermit  # noqa: PLC0415

        rounds = _StillRounds(
            engine=engine,
            storyboard_id=storyboard_id,
            correlation_id=correlation_id,
            adapter=image_adapter,
            model_id=model_id,
            first_live=first_live,
            figure_one=figure_one,
            figure_location=figure_location,
            per_image=per_image,
            overhead=float(prices.round_overhead("image", model_id)),
            credit_usd=float(prices.credit_usd),
            ledger=ledger,
            limit=limit,
            work_dir=work_dir,
            environment=environment,
            registry=registry,
            judge=judge,
            face_counter=face_counter,
            measure=measure,
            ffmpeg_path=ffmpeg_path,
            faces_forbidden=faces_forbidden,
            rules=rules,
        )
        try:
            gpu = rounds.run(
                deferred,
                permit=StepPermit.from_guard(
                    guard,
                    verdict,
                    action=STILLS_ACTION,
                    step=STILLS_STEP,
                    storyboard_id=storyboard_id,
                    plan_hash=plan_hash,
                    requester=requester,
                    correlation_id=correlation_id,
                    integration_id=integration_id,
                    unasked=unasked,
                ),
                guard=guard,
                stopped=lambda: (
                    "Proprietarul a oprit autonomia; nu se mai cumpără imagini."
                    if stop_requested(engine)
                    else None
                ),
            )
        except MediaProviderError as exc:
            if not exc.unsent:
                raise
            # The GPU was not switched on, or the round could not even be sent: nothing was
            # bought, nothing is booked (the caller lets the hold go).
            raise StillsStageRefused(
                str(exc.code or "COMPUTE_NOT_READY"),
                str(getattr(exc, "reason_ro", None) or exc),
                plan=plan,
            ) from exc
        stopped = stopped or gpu.get("stopped")
        unverified = unverified or rounds.unverified

    after: float | None = None
    measured: float | None = None
    if read:
        _read, after, _problem = _read_balance(image_adapter)
        if before is not None and after is not None and before - after > 0:
            measured = before - after
    if measured is not None and ledger.images:
        each = measured / ledger.images
        with Session(engine) as session, session.begin():
            # Read-then-write after a purchase: the write lock first (app.db.lock_for_write).
            lock_for_write(session)
            for take_id in ledger.take_ids:
                row = session.get(SceneTake, take_id)
                if row is not None and row.sha256:
                    row.credits_measured = each
        if integration_id:
            record_measured_prices(
                engine,
                integration_id,
                {integration_id: {"kind": "runway", "balance": before}},
                {integration_id: {"kind": "runway", "balance": after}},
                [
                    {
                        "kind": "still",
                        "model_id": model_id,
                        "resolution": STILLS_RESOLUTION,
                        "count": ledger.images,
                    }
                ],
                table=prices,
            )

    needs_owner = [
        e["scene_index"] for e in results if e.get("status") == "NEEDS_OWNER" and not e.get("held")
    ]
    summary = {
        "storyboard_id": storyboard_id,
        "plan_hash": plan_hash,
        "model_id": model_id,
        "ratio": STILL_RATIO,
        "scenes": results,
        "bought_images": ledger.images,
        "spent_credits_quoted": round(ledger.committed, 4),
        "spent_credits_measured": measured,
        "balance_before": before,
        "balance_after": after,
        "cap_credits": cap,
        "needs_owner": needs_owner,
        "stopped": stopped,
        # The Owner's mode or rule changed while the step ran (`mode_guard`), or None.
        "mode_stopped": guard.stopped if guard is not None else None,
        # The scene the balance stopped, the balance read and what was needed (or None).
        "low_balance": low_balance,
        "reference_unverified": unverified,
        # Requests still open at the vendor (collected later, never bought again), and what
        # was collected before this step looked at anything.
        "in_flight": [e["scene_index"] for e in results if e.get("status") == "IN_FLIGHT"],
        "collected": collected,
        # RunPod Serverless: the rounds, the GPU session's jobs and the billed estimate.
        "gpu": gpu,
    }
    _event(engine, "media.stills_step_finished", storyboard_id, summary, correlation_id)
    return summary
