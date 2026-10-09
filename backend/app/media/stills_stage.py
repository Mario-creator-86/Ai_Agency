"""The stills step: the first, cheapest stair of the money staircase.

Nothing is animated until someone has looked at its still. The Nepal film (2026-09-26) paid
for twelve clips before anybody looked at a picture: three stills showed faces the visual
bible forbade, a bar chart came back as a woman, a black screen as a landscape, and the whole
film was then bought a second time with the same prompts. A still costs 9 credits at 2K; the
clip made from it up to 68 credits a second. So the still is bought first, on its own, and
judged before any motion is priced.

What this step does, in order, and what stops it:

1. The plan (`stills_plan`): every LIVE scene's still prompt exactly as it will be sent, the
   model (seedream5_pro), the ratio (1530:2720, i.e. 2K), two candidates per scene, at most
   two re-rolls, and the credits: the expected round and the cap (the round plus two
   re-rolls). A scene that already holds an APPROVED take for its prompt is not bought again
   and costs 0. Its sha256 is the plan_hash the Owner's yes is bound to.
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
6. A scene with no passing candidate is bought again at most twice (MAX_REROLLS), with what
   was wrong rewritten as positive words (`still_gate.positive_instruction`), then marked
   NEEDS_OWNER with a WARNING event. A vendor refusal follows its kind
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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db import lock_for_write
from app.media.assembler import (
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
    classify_vendor_failure,
    collect_submitted_takes,
    failure_code_of,
    failure_detail_of,
    gpu_seconds_to_credits,
    identity_key,
    max_paid_attempts_per_scene,
    outcome_unknown,
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
from app.media.mode_guard import PurchaseGuard, unasked_refusal
from app.media.models import SceneTake, Storyboard, StoryboardScene
from app.media.picture_qc import StillJudgement, judge_still
from app.media.prompt_lint import (
    BLOCK,
    LintScene,
    bible_face_rule,
    has_block,
    lint_film,
    summary_ro,
)
from app.media.still_gate import (
    ALL_CHECKS,
    COLOUR_WORDS,
    MAX_REROLLS,
    StillPlan,
    StillReport,
    choose_best,
    decide,
    local_checks,
    next_step,
    positive_instruction,
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


@dataclass
class _Ledger:
    """What the step has committed, against the approved cap. ``meter`` is the caller's
    (`assembler.SpendMeter`): the credits committed and the requests sent live there, so a
    caller reads them when the step raises half-way."""

    cap: int
    meter: SpendMeter = field(default_factory=SpendMeter)
    images: int = 0
    take_ids: list[str] = field(default_factory=list)

    @property
    def committed(self) -> float:
        return self.meter.committed

    @committed.setter
    def committed(self, value: float) -> None:
        self.meter.committed = value


# ------------------------------------------------------------------------------ the plan


def _usd_ro(amount: float) -> str:
    """«2,16 USD»: an amount in the Owner's question, with a decimal comma."""
    return f"{float(amount):.2f}".replace(".", ",") + " USD"


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _read_scenes(engine: Engine, storyboard_id: str) -> tuple[dict[str, Any], list[_Scene]]:
    """The film's scenes as the step reads them: each LIVE scene's still identity (its words
    and the reference picture of the character it shows, the identity `assemble_from_takes`
    looks for), its approved still, what was bought and not settled, and what it remembers
    since the Owner last decided about it (`assembler.scene_memory`)."""
    from app.media.services import ReferenceRequired  # noqa: PLC0415 - services imports media

    loaded: dict[str, bytes] = {}
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise ValueError(f"Storyboard {storyboard_id} not found")
        bible = dict(board.visual_bible_json or {})
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
            scenes.append(scene)
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
    return bible, scenes


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
    cap = cost * (1 + MAX_REROLLS)
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
        cap += overhead * series * (1 + MAX_REROLLS)
    planned = {
        "storyboard_id": storyboard_id,
        "step": STILLS_STEP,
        "model_id": model_id,
        "ratio": STILL_RATIO,
        "resolution": STILLS_RESOLUTION,
        "candidates": STILL_CANDIDATES,
        "max_rerolls": MAX_REROLLS,
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


def _references(
    scene: _Scene, figure_one: bytes | None, adapter: Any, *, first: bool
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
    with_figure = figure_one is not None and not first
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
        plan = StillPlan(
            scene=scene.index,
            still_prompt=scene.words,
            camera_move=scene.camera_move,
            faces_forbidden=faces_forbidden,
            bible_rules=rules,
            look_block=scene.look_block,
            palette_words=_palette_words(scene.look_block),
        )
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
        best = choose_best([report for _take, report in verdicts])
        _set_verdicts(engine, verdicts, best)
        if best is not None:
            chosen = next(take for take, report in verdicts if report is best)
            return {
                "status": "APPROVED",
                "take_id": chosen,
                "score": best.score,
                "credits": 0,
                "judged_collected": len(verdicts),
                "path": str(best.path),
            }
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

    # ------------------------------------------------------------------ requests

    def _prepare(self, state: _SceneRound) -> None:
        refs, with_character, with_figure = _references(
            state.scene,
            self.figure_one,
            self.adapter,
            first=state.scene.index == self.first_live,
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
            scene, _ANY_FIGURE, self.adapter, first=False
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
                negative_prompt=None,
                seed=item_seed(self.storyboard_id, state.scene.index, state.attempt, candidate),
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
        state.requests += 1
        state.verdicts, state.failed = [], []
        return self._requests(state)

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
        best = choose_best(reports)
        _set_verdicts(self.engine, state.verdicts, best)
        if best is not None:
            chosen = next(take for take, report in state.verdicts if report is best)
            if state.scene.index == self.first_live:
                self.figure_one = Path(best.path).read_bytes()
            state.outcome = {"status": "APPROVED", "take_id": chosen, "score": best.score}
            return None
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
        failing = next((r for r in reports if r.violations), reports[0])
        step = next_step(failing, rerolls_done=state.rerolls)
        if step.action == "reroll":
            state.rerolls += 1
            state.instruction = positive_instruction(
                [code for report in reports for code in report.violations]
            )
            return "again"
        if step.action == "compose_locally":
            state.outcome = {"status": "COMPOSE_LOCALLY", "reason": step.reason_ro}
            return None
        state.outcome = {
            "status": "NEEDS_OWNER",
            "reason": step.reason_ro,
            "reasons": list(dict.fromkeys(r for rep in reports for r in rep.reasons_ro)),
        }
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

    def run(
        self,
        deferred: list[tuple[_Scene, dict[str, Any]]],
        *,
        permit: Any,
        guard: PurchaseGuard | None,
        stopped: Callable[[], str | None],
    ) -> dict[str, Any]:
        from app.media.gpu_batch import run_rounds  # noqa: PLC0415 - gpu_batch reads runpod

        buying = {scene.index for scene, _entry in deferred}
        first: list[BatchRequest] = []
        for scene, entry in deferred:
            state = _SceneRound(
                scene=scene,
                entry=entry,
                still_plan=StillPlan(
                    scene=scene.index,
                    still_prompt=scene.words,
                    camera_move=scene.camera_move,
                    faces_forbidden=self.faces_forbidden,
                    bible_rules=self.rules,
                    look_block=scene.look_block,
                    palette_words=_palette_words(scene.look_block),
                ),
                identity=take_hash(scene.identity, self.model_id),
                requests=scene.attempts,
                committed_before=self.ledger.committed,
            )
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
            summary = run_rounds(
                self.engine,
                self.adapter,
                permit=permit,
                purpose="image",
                first_round=first,
                next_round=self.next_round,
                price_credits=self.price,
                cap_left=lambda: float(self.ledger.cap) - self.ledger.committed,
                guard=guard,
                stopped=stopped,
                on_submitted=self.submitted,
                on_outcome=self.landed,
                meter=self.ledger.meter,
                credits_for_seconds=gpu_seconds_to_credits(
                    self.adapter, credit_usd=self.credit_usd
                ),
                on_unsent=self.unsent,
            )
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
            LintScene(scene=scene.index, kind=scene.kind, still_prompt=scene.words)
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
    ledger = _Ledger(cap=cap, meter=meter if meter is not None else SpendMeter())
    limit = max_paid_attempts_per_scene()
    figure_one: bytes | None = None
    first_live = live[0].index if live else None
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
        still_plan = StillPlan(
            scene=scene.index,
            still_prompt=scene.words,
            camera_move=scene.camera_move,
            faces_forbidden=faces_forbidden,
            bible_rules=rules,
            look_block=scene.look_block,
            palette_words=_palette_words(scene.look_block),
        )
        references, with_character, with_figure = _references(
            scene, figure_one, image_adapter, first=scene.index == first_live
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
            if requests >= limit:
                outcome = {
                    "status": "NEEDS_OWNER",
                    "reason": attempts_reason(scene.index, requests, limit),
                }
                break
            if ledger.committed + per_request > ledger.cap:
                stopped = (
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
            reports = [report for _take, report in verdicts]
            best = choose_best(reports)
            _set_verdicts(engine, verdicts, best)
            if best is not None:
                chosen = next(take for take, report in verdicts if report is best)
                if scene.index == first_live:
                    figure_one = Path(best.path).read_bytes()
                outcome = {"status": "APPROVED", "take_id": chosen, "score": best.score}
                break
            failing = next((r for r in reports if r.violations), reports[0] if reports else None)
            if failing is None:
                outcome = {
                    "status": "NEEDS_OWNER",
                    "reason": f"Scena {scene.index}: furnizorul nu a dat nicio imagine.",
                }
                break
            step = next_step(failing, rerolls_done=rerolls)
            if step.action == "reroll":
                rerolls += 1
                violations = [code for report in reports for code in report.violations]
                instruction = positive_instruction(violations)
                continue
            if step.action == "compose_locally":
                outcome = {"status": "COMPOSE_LOCALLY", "reason": step.reason_ro}
                break
            outcome = {
                "status": "NEEDS_OWNER",
                "reason": step.reason_ro,
                "reasons": list(dict.fromkeys(r for rep in reports for r in rep.reasons_ro)),
            }
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
