"""Foaia de filmare: the page in front of every purchase, and the steps it gates.

The second Nepal render (2026-09-26, 18:16) started from a button that showed no price, no
prompt and no model, asked nothing, and bought every still and every clip of the film again.
The shooting sheet is what the Owner sees before a credit is spent, built at 0 credits: the
only live call is the free Runway balance read (GET /v1/organization).

Per scene it shows the kind; the chosen still (or the card's verified numbers) and the
candidates that were not chosen, with their reasons; the still prompt and the motion prompt
exactly as they will be sent; the lint findings, quoting their evidence in Romanian; the
check badges; the model chosen for THAT scene (production_policy.plan_scene_models, the
Owner's decision of 2026-09-27: the cheapest capable model, premium only where the scene
needs it, his own choice winning) with its reason, whole seconds, the film's seed, the
credits and USD and where the price comes from ("tarif publicat dd.mm", "măsurat",
"nevalidat"), and the cheaper and the better alternative with their prices. A card scene
reads "Grafic compus local · 0 credite".

The footer has what the stills already cost, the hero test shot, the rest of the motion, the
total, the hard cap, the live balance, the daily budget's remainder, the saving against the
premium model everywhere, the whole film priced at 720p, on seedance2 and on veo3.1_fast,
and the ``sheet_hash``: the sha256 of the canonical JSON of what will be bought and how
(prompts, still sha256s, models, resolution, seconds, seed, kinds, credits, the Owner's
choices and each step's purchase). Every paid step's yes is bound to that hash
(``run_sheet_step``): a changed prompt, still, model, price or take is a new sheet, and a yes
for the old one buys nothing.

The three steps, each its own approval of the Owner bound to the hash (OWNER_GATE):

=========  =========================  ====
stills     media.stills_purchase      T2
test_shot  media.test_shot            T3
motion     media.motion_purchase      T3
=========  =========================  ====

Before a step is handed to its stage (stills_stage.run_stills_stage, or the assembler's
run_motion_step), the sheet refuses, with a Romanian reason: a stale hash, an open lint
BLOCK, a film whose shots a model did not write (PRODUCTION), a Runway balance below the
step's cap x 1.15 (or one that could not be read), and a step that would exceed the daily
budget without the Owner's explicit consent. The stage then asks the Owner (202) or spends
his yes and buys (200).
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import logging
import subprocess
import tempfile
import threading
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.media.assembler import (
    CLIP_SHORT,
    HERO_ACCEPTED_BY,
    MOTION_STEP,
    MOTION_STEP_ACTIONS,
    SHOT_TAKE_KINDS,
    STEP_ROUND_WORDS,
    TEST_SHOT_STEP,
    MotionStepRefused,
    SceneRedoRefused,
    SpendMeter,
    SpentStageError,
    assembly_readiness,
    check_unchecked_shots,
    clip_plan,
    clip_qc_of,
    collect_submitted_takes,
    decide_take,
    film_seed,
    hero_acceptances,
    hero_gate,
    latest_assembly_refusal,
    motion_plan,
    motion_seconds,
    narration_to_buy,
    owner_take_decisions,
    redo_plan,
    release_after_qc,
    run_motion_step,
    scene_kind_of,
    scene_view,
    shot_clip_seconds,
    shot_plan_sources,
    still_options,
    usable_take,
    voiced_scenes,
)
from app.media.balance_rule import (
    DEFAULT_MARGIN,
    LOW_BALANCE,
    margin_of,
    missing_credits,
    needed_credits,
    record_balance_reading,
    round_line_ro,
    start_refusal_ro,
)
from app.media.cards import CARD_KINDS, CardError, card_spec_from_json, compose_card
from app.media.cost_plan import (
    MEASURED,
    STILL_CANDIDATES,
    STILLS_MODEL,
    STILLS_RESOLUTION,
    PriceRow,
    PriceTable,
    UnpricedError,
    credits_to_micros,
    load_price_table,
    longest_seconds,
    plan_film,
    price_still,
    source_label,
)
from app.media.models import FilmPurchaseLease, SceneTake, Storyboard, StoryboardScene
from app.media.production_policy import (
    COMPOSED_LABELS_RO,
    LOCAL_MOVE,
    SCENE_TOO_LONG,
    ModelCapability,
    load_film_models,
    need_from_scene,
    plan_scene_models,
)
from app.media.prompt_lint import (
    BLOCK,
    Finding,
    LintScene,
    bible_face_rule,
    has_block,
    lint_film,
    summary_ro,
)
from app.media.sheet_words import blocked_words, decision_outcome, refusal_view
from app.media.stills_stage import (
    STILLS_ACTION,
    STILLS_STEP,
    StillsStageRefused,
    needs_reference_reason,
    run_stills_stage,
    settle_stills,
    stills_plan,
)
from app.media.toolchain import find_ffmpeg
from app.providers.runpod.batch import OVERHEAD_LINE_RO
from app.wording import count as count_ro

logger = logging.getLogger("studio.media.sheet")

__all__ = [
    "ASSEMBLE_STEP",
    "LOCAL_MOVE",
    "SHEET_STEPS",
    "book_interrupted_step",
    "book_purchase",
    "book_step_cost",
    "may_spend_step",
    "purchase_reference",
    "narration_gate",
    "recover_paid_takes",
    "run_assemble_step",
    "withdraw_stale_questions",
    "connection_account",
    "connection_capabilities",
    "connection_video_adapters",
    "runway_connection_id",
    "SheetNotFound",
    "SheetChoiceRefused",
    "SheetStepRefused",
    "build_sheet",
    "card_preview_png",
    "decide_sheet_take",
    "price_table_for",
    "run_sheet_step",
    "set_scene_model",
    "sheet_hash",
    "sheet_overrides",
    "sheet_url",
]

#: The paid steps of the staircase, in order.
SHEET_STEPS: tuple[str, ...] = (STILLS_STEP, TEST_SHOT_STEP, MOTION_STEP)
#: The last step: the film assembled from its takes, its narration voiced, its QC and letter.
ASSEMBLE_STEP = "assemble"
#: The narration's question in the Policy Kernel: a paid generation, over the Owner's
#: threshold or within it (the actions the day's narration was already asked under).
NARRATION_ACTION = "media.paid_generation"
NARRATION_ACTION_OVER = "media.paid_generation_over_threshold"
#: The event that says an older sheet's question was withdrawn by a newer one.
WITHDRAWN_EVENT = "governance.approval_withdrawn"
#: The event of a film assembled from the sheet.
ASSEMBLED_EVENT = "media.sheet_assembled"
#: Each step's action in the Policy Kernel (and so its tier and its Owner's question).
SHEET_STEP_ACTIONS: dict[str, str] = {STILLS_STEP: STILLS_ACTION, **MOTION_STEP_ACTIONS}
#: The Owner's words for each step of the sheet.
STEP_WORDS_RO: dict[str, str] = {
    STILLS_STEP: "imaginile",
    TEST_SHOT_STEP: "cadrul de probă",
    MOTION_STEP: "restul mișcării",
    ASSEMBLE_STEP: "narațiunea și asamblarea",
}
#: The account must hold this much more than a step's next round before the step is asked
#: or bought (the Owner's rule of 2026-10-03, `balance_rule`); the cap stays its ceiling.
BALANCE_MARGIN = DEFAULT_MARGIN
#: Each paid step in the sentence «Runda următoare a ... costă ...».
ROUND_WORDS_RO: dict[str, str] = {STILLS_STEP: "pasului de imagini", **STEP_ROUND_WORDS}
#: The film's resolution unless the Owner's settings name another.
SHEET_RESOLUTION = "1080p"
#: The event that records the Owner's per-scene model choice (read back, last one wins).
SCENE_MODEL_EVENT = "media.sheet_scene_model_set"
#: The only issuer of a per-scene choice and of a take's verdict.
OWNER = "owner"
#: The budget period words of the Owner's page.
PERIOD_WORDS = {"DAILY": "zilnic", "MONTHLY": "lunar"}
#: The light the look block names, in the Owner's words, for the sheet's badge.
LIGHT_WORDS: tuple[tuple[str, str], ...] = (
    ("overcast", "înnorat"),
    ("cloud", "înnorat"),
    ("fog", "ceață"),
    ("mist", "ceață"),
    ("dusk", "amurg"),
    ("sunset", "amurg"),
    ("dawn", "zori"),
    ("sunrise", "zori"),
    ("night", "noapte"),
    ("sun", "însorit"),
)


class SheetNotFound(LookupError):
    """The storyboard, its scene or its take does not exist (404)."""


class SheetChoiceRefused(ValueError):
    """The Owner's choice on the sheet cannot be taken as given (422), said in Romanian."""


class SheetStepRefused(RuntimeError):
    """A step bought nothing. ``status`` says why; ``reason_ro`` is the Owner's.

    NEEDS_APPROVAL is a 202 (his question waits, with ``approval_id``, ``cost_usd`` and
    ``cap_credits``); everything else is a 409.
    """

    def __init__(
        self,
        status: str,
        reason_ro: str,
        *,
        approval_id: str | None = None,
        cost_usd: float | None = None,
        cap_credits: int | None = None,
        findings: Sequence[Any] = (),
        scenes: Sequence[dict[str, Any]] = (),
        withdrawn: Sequence[str] = (),
    ) -> None:
        super().__init__(reason_ro)
        self.status = status
        self.reason_ro = reason_ro
        self.approval_id = approval_id
        self.cost_usd = cost_usd
        self.cap_credits = cap_credits
        self.findings = list(findings)
        #: The scenes that keep the step from running, each with its Romanian reason.
        self.scenes = list(scenes)
        #: The older questions this one withdrew (a newer sheet asked for the same step).
        self.withdrawn = list(withdrawn)

    @property
    def http_status(self) -> int:
        return 202 if self.status == "NEEDS_APPROVAL" else 409

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"status": self.status, "message": self.reason_ro}
        if self.status == "NEEDS_APPROVAL":
            body.update(
                approval_id=self.approval_id,
                cost_usd=self.cost_usd,
                cap_credits=self.cap_credits,
                withdrawn=self.withdrawn,
            )
        if self.scenes:
            body["scenes"] = self.scenes
        if self.findings:
            body["findings"] = [
                finding.as_dict() if hasattr(finding, "as_dict") else finding
                for finding in self.findings
            ]
        return body


@dataclass(frozen=True)
class _Context:
    """What the sheet and its steps are computed from; the same on the GET and the POST."""

    capabilities: tuple[ModelCapability, ...]
    table: PriceTable
    integration_id: str | None
    allowed: frozenset[str] | None
    resolution: str
    stills_model: str
    today: date | None


def sheet_url(storyboard_id: str) -> str:
    return f"/api/v1/media/storyboards/{storyboard_id}/shooting-sheet"


def price_table_for(engine: Engine, integration_id: str | None) -> PriceTable:
    """The published table, with this Runway connection's MEASURED prices laid over it."""
    from app.economy.credits import measured_price_table  # noqa: PLC0415 - economy imports media
    from app.media.local_media import local_prices  # noqa: PLC0415
    from app.providers.runpod.pricing import estimated_prices  # noqa: PLC0415

    table: PriceTable = (
        measured_price_table(engine, integration_id) if integration_id else load_price_table()
    )
    return estimated_prices(engine, local_prices(engine, table))


def _context(
    engine: Engine,
    *,
    capabilities: Iterable[ModelCapability] | None,
    integration_id: str | None,
    table: PriceTable | None,
    allowed: Iterable[str] | None,
    resolution: str | None,
    stills_model: str | None,
    today: date | None,
) -> _Context:
    return _Context(
        capabilities=tuple(capabilities or ()),
        table=table if table is not None else price_table_for(engine, integration_id),
        integration_id=integration_id,
        allowed=frozenset(allowed) if allowed is not None else None,
        resolution=resolution or SHEET_RESOLUTION,
        stills_model=stills_model or STILLS_MODEL,
        today=today,
    )


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _ro_usd(micros: int) -> str:
    return f"{micros / 1_000_000:.2f}".replace(".", ",") + " USD"


def _ro_credits(value: int) -> str:
    number = int(value)
    rest = abs(number) % 100
    joiner = " de " if number >= 20 and (rest == 0 or rest >= 20) else " "
    return f"{number:,}".replace(",", ".") + f"{joiner}credite"


def _source_of(rows: Iterable[PriceRow], today: date | None) -> str:
    """One label for several prices: 'nevalidat' if any is, 'măsurat' if all are, else the
    oldest published day."""
    used = list(rows)
    if not used:
        return ""
    labels = [source_label(row, today=today) for row in used]
    if "nevalidat" in labels:
        return "nevalidat"
    documented = [row for row in used if row.provenance != MEASURED]
    if not documented:
        return "măsurat"
    return source_label(min(documented, key=lambda row: row.date), today=today)


# ------------------------------------------------------------------ the Owner's choices


def sheet_overrides(engine: Engine, storyboard_id: str) -> dict[int, str | None]:
    """The Owner's per-scene model choices on the sheet (a model id or LOCAL_MOVE).

    Read from his own events, the last one per scene winning; a choice set back to None is
    the policy's again.
    """
    from app.models import DomainEvent  # noqa: PLC0415

    chosen: dict[int, str | None] = {}
    with Session(engine) as session:
        for event in session.scalars(
            select(DomainEvent)
            .where(
                DomainEvent.event_type == SCENE_MODEL_EVENT,
                DomainEvent.aggregate_id == storyboard_id,
            )
            .order_by(DomainEvent.sequence)
        ):
            payload = event.payload if isinstance(event.payload, dict) else {}
            index = payload.get("scene_index")
            if isinstance(index, int):
                model = payload.get("model_id")
                chosen[index] = str(model) if model else None
    kept: dict[int, str | None] = {index: model for index, model in chosen.items() if model}
    return kept


def set_scene_model(
    engine: Engine,
    storyboard_id: str,
    scene_index: int,
    model_id: str | None,
    *,
    issued_by: str,
    note: str | None = None,
    table: PriceTable | None = None,
    resolution: str = SHEET_RESOLUTION,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """The Owner chooses a filmed scene's motion model on the sheet, or LOCAL_MOVE.

    Only he does (``issued_by`` is the route's, after his key). A card has no motion model;
    a model the price table cannot price at the film's resolution is refused, never guessed.
    The choice is an event: it changes the sheet and so its hash.
    """
    from uuid import uuid4  # noqa: PLC0415

    from app.services import append_event  # noqa: PLC0415 - services imports media

    if issued_by != OWNER:
        raise PermissionError(
            "Doar Proprietarul alege modelul unei scene pe foaia de filmare; "
            f"cererea venită de la «{issued_by or 'necunoscut'}» nu a schimbat nimic."
        )
    prices = table if table is not None else load_price_table()
    with Session(engine) as session, session.begin():
        scene = session.scalars(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id,
                StoryboardScene.scene_index == int(scene_index),
            )
        ).first()
        if scene is None:
            raise SheetNotFound(f"Scena {scene_index} nu există în acest storyboard.")
        kind = scene_kind_of({"scene_kind": scene.scene_kind})
        if kind != "LIVE":
            raise SheetChoiceRefused(
                f"Scena {scene_index} este {COMPOSED_LABELS_RO.get(kind, kind).lower()} "
                "compus local, cu 0 credite; nu are model de mișcare de ales."
            )
        if model_id and model_id != LOCAL_MOVE:
            try:
                row = prices.row(model_id, resolution)
            except UnpricedError:
                row = None
            if row is None or row.kind != "video" or row.credits_per_second is None:
                raise SheetChoiceRefused(
                    f"Modelul {model_id} nu are preț publicat la {resolution}; nu poate fi "
                    "ales pentru o scenă, fiindcă nu se cumpără nimic pe un preț ghicit."
                )
        event = append_event(
            session,
            SCENE_MODEL_EVENT,
            "storyboard",
            storyboard_id,
            1,
            {
                "scene_index": int(scene_index),
                "model_id": model_id or None,
                "decided_by": OWNER,
                "note": (note or "").strip()[:500] or None,
            },
            correlation_id or str(uuid4()),
        )
        # His choice is often the decision the film waits for (a scene held for him, now a
        # local move): the film is walked on now, as his take decisions and his paid yes
        # already walk it. 2026-10-10: he chose LOCAL_MOVE for babcf272's scene 5 at 08:46 UTC
        # and nothing moved, because only those two queued the continuation. Nothing is
        # bought by this: the walk asks for anything paid under his rule. PRODUCTION only.
        from app.services import queue_film_continue  # noqa: PLC0415 - services imports media

        continue_task_id = queue_film_continue(
            session,
            storyboard_id,
            key=f"film-continue-{storyboard_id}-scene-model-{event.event_id}",
            payload={"cause": f"scene_model:{int(scene_index)}:{model_id or 'auto'}"},
        )
    return {
        "scene_index": int(scene_index),
        "model_id": model_id or None,
        "continue_task_id": continue_task_id,
    }


def decide_sheet_take(
    engine: Engine,
    take_id: str,
    decision: str,
    *,
    note: str | None = None,
    final: bool = False,
    correlation_id: str | None = None,
    sheet_reader: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The Owner's look at a take on the contact sheet: APPROVED or REJECTED.

    ``final`` marks his APPROVED final (2026-10-11): the Director's confirmed repair replaces
    a take he approved, telling him, unless he marked it final (`decide_take`).

    Approving a still makes it THE still of its scene for its prompt: any other approved still
    of that scene and prompt goes back to PAID (kept, never deleted), so one scene never has
    two pictures the motion could start from.

    The answer carries ``outcome`` (`sheet_words.decision_outcome`): what the choice did and
    what the continuation it queued will do. ``sheet_reader(storyboard_id)`` reads the sheet
    with no live call so the next step can be named; without it the step goes unnamed.

    A closed film (`film_is_closed`) is refused: `SheetStepRefused` FILM_CLOSED, nothing changed.
    """
    from uuid import uuid4  # noqa: PLC0415

    from app.services import append_event, utc_now  # noqa: PLC0415 - services imports media

    with Session(engine) as session:
        take = session.get(SceneTake, take_id)
        if take is None:
            raise SheetNotFound("Înregistrarea nu există.")
        kind, storyboard_id, scene, identity = (
            take.kind,
            take.storyboard_id,
            take.scene_number,
            take.prompt_hash,
        )
    correlation = correlation_id or str(uuid4())
    try:
        result = decide_take(
            engine,
            take_id,
            decision,
            decided_by=OWNER,
            note=note,
            correlation_id=correlation,
            final=final,
        )
    except FilmClosed as exc:
        # «Închide filmul»: a closed film's takes are no longer chosen, and nothing continues
        # (409). The page hides their buttons; this answers a press from an older page.
        raise SheetStepRefused(exc.status, exc.reason_ro) from exc
    superseded: list[str] = []
    if decision == "APPROVED" and kind == "still":
        with Session(engine) as session, session.begin():
            for other in session.scalars(
                select(SceneTake).where(
                    SceneTake.storyboard_id == storyboard_id,
                    SceneTake.scene_number == scene,
                    SceneTake.kind == "still",
                    SceneTake.prompt_hash == identity,
                    SceneTake.status == "APPROVED",
                    SceneTake.id != take_id,
                )
            ):
                other.status = "PAID"
                other.approved_by = None
                other.updated_at = utc_now()
                superseded.append(other.id)
            if superseded:
                append_event(
                    session,
                    "media.scene_take_superseded",
                    "storyboard",
                    storyboard_id,
                    1,
                    {"scene_number": scene, "chosen": take_id, "superseded": superseded},
                    correlation,
                )
    # 2026-10-04: the answer says what the choice set going (the FILM_CONTINUE decide_take
    # queued, and what it will buy under his rule), read from the sheet as it is now.
    sheet = None
    if result.get("continue_task_id") and sheet_reader is not None:
        try:
            sheet = sheet_reader(storyboard_id)
        except Exception:  # noqa: BLE001 - the decision stands; only the step goes unnamed
            logger.warning("take_outcome_sheet_unread", extra={"storyboard_id": storyboard_id})
    outcome = decision_outcome(
        engine,
        kind=kind,
        scene_number=int(scene),
        decision=decision,
        continue_task_id=result.get("continue_task_id"),
        sheet=sheet,
        storyboard_id=storyboard_id,
    )
    return {
        **result,
        "superseded": superseded,
        "storyboard_id": storyboard_id,
        "scene_number": int(scene),
        "decision": decision,
        "outcome": outcome,
    }


# ------------------------------------------------------------------------- the sheet


def _read_balance(account: Any) -> dict[str, Any]:
    from app.media.local_media import is_local  # noqa: PLC0415

    if getattr(account, "billing_mode", None) == "gpu":
        return {
            "credits": None,
            "read": False,
            "problem": None,
            "applicable": False,
            "billing_mode": "gpu",
            "note": "Cost GPU estimat; bugetul Agency se aplică.",
        }
    if is_local(account):
        return {
            "credits": None,
            "read": False,
            "problem": None,
            "applicable": False,
            "billing_mode": "local",
        }
    """The live Runway balance: one free GET. Never raises; a failure is named."""
    reader = getattr(account, "credit_balance", None)
    if not callable(reader):
        return {"credits": None, "read": False, "problem": "niciun cont Runway conectat"}
    try:
        balance = asyncio.run(reader())
    except Exception as exc:  # noqa: BLE001 - any failure to read is reported, never 0
        return {
            "credits": None,
            "read": False,
            "problem": f"soldul Runway nu a putut fi citit ({str(exc)[:120]})",
        }
    if isinstance(balance, bool) or not isinstance(balance, int | float):
        return {"credits": None, "read": True, "problem": "Runway nu a spus soldul"}
    return {"credits": float(balance), "read": True, "problem": None}


def _daily_budget(engine: Engine) -> dict[str, Any] | None:
    from app.economy.budget import budget_status  # noqa: PLC0415 - economy imports media

    for period in budget_status(engine)["budgets"]:
        if period["period"] == "DAILY":
            return {
                "limit_usd": period["limit_usd"],
                "spent_usd": period["spent_usd"],
                "reserved_usd": period["reserved_usd"],
                "remaining_usd": period["remaining_usd"],
                "remaining_usd_micros": period["remaining_usd_micros"],
                "state": period["state"],
            }
    return None


def _light_badge(look_block: str) -> str:
    text = look_block.lower()
    for word, label in LIGHT_WORDS:
        if word in text:
            return label
    return "nedefinită"


def _badges(
    *,
    still_prompt: str,
    look_block: str,
    faces_forbidden: bool,
    still_path: str | None,
    face_findings: bool,
    face_counter: Callable[..., Any] | None,
) -> list[dict[str, str]]:
    """What the sheet can say about a scene's picture, and how it knows it."""
    badges: list[dict[str, str]] = []
    if faces_forbidden:
        if still_path and face_counter is not None and Path(still_path).is_file():
            counted = face_counter(Path(still_path))
            if getattr(counted, "status", None) == "MEASURED":
                faces = int(counted.faces or 0)
                value = "da" if faces == 0 else f"nu ({faces})"
                badges.append(
                    {"code": "faces", "label_ro": f"fără fețe: {value}", "source": "măsurat"}
                )
            else:
                badges.append(
                    {
                        "code": "faces",
                        "label_ro": "fără fețe: nemăsurat",
                        "source": str(getattr(counted, "detail_ro", "") or "nemăsurat"),
                    }
                )
        else:
            value = "nu e cerut corect" if face_findings else "cerut în prompt"
            badges.append({"code": "faces", "label_ro": f"fără fețe: {value}", "source": "prompt"})
    asks_no_text = "no text" in still_prompt.lower()
    badges.append(
        {
            "code": "text",
            "label_ro": "fără text: " + ("cerut în prompt" if asks_no_text else "nu e cerut"),
            "source": "prompt",
        }
    )
    badges.append(
        {"code": "light", "label_ro": f"lumină: {_light_badge(look_block)}", "source": "prompt"}
    )
    return badges


def _file_url(take_id: str) -> str:
    return f"/api/v1/media/takes/{take_id}/file"


def _scene_takes(session: Session, storyboard_id: str) -> dict[int, list[SceneTake]]:
    found: dict[int, list[SceneTake]] = {}
    for take in session.scalars(
        select(SceneTake)
        .where(SceneTake.storyboard_id == storyboard_id)
        .order_by(SceneTake.scene_number, SceneTake.created_at)
    ):
        found.setdefault(int(take.scene_number), []).append(take)
    return found


#: How the sheet names a take accepted by its clip QC under the Owner's rule.
ACCEPTED_BY_CLIP_QC_RO = "acceptat de controlul clipului"


def _take_view(
    take: SceneTake,
    *,
    current: bool,
    clip_qc: dict[str, Any] | None = None,
    accepted_by: str | None = None,
    final: bool = False,
) -> dict[str, Any]:
    return {
        "take_id": take.id,
        "kind": take.kind,
        "status": take.status,
        "model_id": take.model_id,
        "resolution": take.resolution,
        "seconds": take.seconds,
        "seed": take.seed,
        "sha256": take.sha256,
        "credits_quoted": take.credits_quoted,
        "credits_measured": take.credits_measured,
        "failure_code": take.failure_code,
        "reason_ro": take.failure_detail,
        "approved_by": take.approved_by,
        # His approval marked final (2026-10-11): no repair of the Director's replaces it.
        "owner_final": final,
        "for_current_prompt": current,
        "file_url": _file_url(take.id) if take.path else None,
        # A shot's clip-QC report as it was kept on its take (None for a still, or a shot
        # nobody checked yet): what the Owner's look on the contact sheet is about.
        "clip_qc": clip_qc,
        # A hero test shot accepted by that report under his paid-media rule (HERO_AUTO_ACCEPT,
        # 2026-10-02): still PAID, never APPROVED, which stays his.
        "accepted_by": accepted_by,
        "accepted_ro": ACCEPTED_BY_CLIP_QC_RO if accepted_by == HERO_ACCEPTED_BY else None,
        # A vendor's refusal in his words, its text once and what it cost (2026-10-04).
        "refusal": (
            refusal_view(
                take.failure_code,
                take.failure_detail,
                take.credits_measured,
                take.credits_quoted,
            )
            if take.status == "REFUSED"
            else None
        ),
    }


def _stills_spent(takes: dict[int, list[SceneTake]]) -> dict[str, Any]:
    quoted = 0.0
    measured = 0.0
    any_measured = False
    for rows in takes.values():
        for take in rows:
            if take.kind != "still" or take.status == "QUOTED":
                continue
            quoted += float(take.credits_quoted or 0.0)
            if take.credits_measured is not None:
                any_measured = True
                measured += float(take.credits_measured)
    return {
        "quoted_credits": round(quoted, 4),
        "measured_credits": round(measured, 4) if any_measured else None,
    }


def _alternatives(
    policy: dict[str, Any], ctx: _Context, stills_row: PriceRow | None
) -> list[dict[str, Any]]:
    scenes = policy.get("plan_film_scenes") or []
    if not any(scene.get("kind") == "LIVE" for scene in scenes):
        return []
    try:
        priced = plan_film(
            scenes, table=ctx.table, today=ctx.today, stills_model=ctx.table.stills_model
        )
    except UnpricedError as exc:
        logger.info("sheet_alternatives_unpriced", extra={"reason": str(exc)[:160]})
        return []
    offered: list[dict[str, Any]] = []
    for alternative in priced["alternatives"]:
        rows: list[PriceRow] = [stills_row] if stills_row is not None else []
        for scene in scenes:
            if scene.get("kind") != "LIVE":
                continue
            model = (
                scene["model_id"]
                if alternative["model_id"] in ("mixt", scene["model_id"])
                else alternative["model_id"]
            )
            try:
                rows.append(ctx.table.row(str(model), str(alternative["resolution"])))
            except UnpricedError:
                continue
        offered.append(
            {
                **alternative,
                "total_usd": round(alternative["total_usd_micros"] / 1_000_000, 6),
                "price_source": _source_of(rows, ctx.today),
            }
        )
    return offered


def _price_line(kind: str, motion: dict[str, Any], credit_usd: float) -> str:
    if kind in CARD_KINDS:
        return f"{COMPOSED_LABELS_RO[kind]} compus local · 0 credite"
    status = motion.get("status")
    if status == "LOCAL":
        return "Mișcare: imagine fixă animată local · 0 credite (doar imaginea se cumpără)"
    if not motion.get("model_id"):
        return f"Fără model ales: {motion.get('reason_ro') or 'decide Proprietarul'}"
    credits = int(motion.get("credits") or 0)
    usd = credits_to_micros(credits, credit_usd)
    line = (
        f"{motion['model_id']} · {motion.get('billed_seconds')} s · {_ro_credits(credits)} "
        f"({_ro_usd(usd)}) · {motion.get('price_source') or 'preț necunoscut'}"
    )
    if status == "BOUGHT":
        line += " · deja cumpărat"
    return line


def _narration(
    session: Session, scenes: Sequence[dict[str, Any]], voiced: set[int] | None = None
) -> dict[str, Any]:
    """The narration's price: its characters at the dearest active ElevenLabs price per
    thousand (the figure the day's estimate holds, `economy.budget.estimate_film_cost_micros`).

    A scene whose words are already voiced (``voiced``, `assembler.voiced_scenes`: a
    narration take of every part of its words as they are now) costs 0: an assembly reuses
    it. It is its own line on the sheet and part of the hashed plan: a new price, or new
    words, is a new sheet. With words and no price it is unpriced, never 0: the step asks.
    """
    from sqlalchemy import func  # noqa: PLC0415

    from app.economy.models import ProviderPrice  # noqa: PLC0415 - economy imports media

    reused = sorted(
        int(scene["scene_index"]) for scene in scenes if int(scene["scene_index"]) in (voiced or ())
    )
    characters = sum(
        len(" ".join(str(scene.get("voiceover_segment") or "").split()))
        for scene in scenes
        if int(scene["scene_index"]) not in reused
    )
    per_1k = session.scalar(
        select(func.max(ProviderPrice.usd_micros)).where(
            ProviderPrice.provider_kind == "elevenlabs",
            ProviderPrice.unit == "per_1k_characters",
            ProviderPrice.active.is_(True),
        )
    )
    micros = (characters * int(per_1k) + 500) // 1000 if per_1k else 0
    priced = bool(per_1k) or characters == 0
    said = count_ro(characters, "caracter", "caractere")
    if characters == 0 and reused:
        line = (
            "Narațiune: deja înregistrată pentru "
            + count_ro(len(reused), "scenă", "scene")
            + " · 0 USD"
        )
    elif characters == 0:
        line = "Narațiune: niciun cuvânt de citit · 0 USD"
    elif priced:
        line = (
            f"Narațiune: {said} · {_ro_usd(micros)} · tarif ElevenLabs "
            f"{_ro_usd(int(per_1k or 0))} la 1.000 de caractere"
        )
    else:
        line = (
            f"Narațiune: {said} · preț necunoscut (niciun tarif ElevenLabs activ); "
            "nu se cumpără fără întrebarea Proprietarului"
        )
    if characters and reused:
        line += (
            " · "
            + count_ro(len(reused), "scenă", "scene")
            + (" deja înregistrată" if len(reused) == 1 else " deja înregistrate")
            + ", 0 USD"
        )
    return {
        "characters": characters,
        "reused_scenes": reused,
        "per_1k_usd_micros": int(per_1k) if per_1k else None,
        "usd_micros": int(micros),
        "usd": round(micros / 1_000_000, 6),
        "priced": priced,
        "line_ro": line,
    }


def _safety_moves(session: Session, storyboard_id: str) -> dict[int, dict[str, Any]]:
    """Per scene, the model the motion step suggested after a SAFETY refusal (the latest one),
    for the Owner to choose on the sheet: nothing is bought on a suggestion."""
    from app.models import DomainEvent  # noqa: PLC0415

    moves: dict[int, dict[str, Any]] = {}
    for event in session.scalars(
        select(DomainEvent)
        .where(
            DomainEvent.event_type == "media.motion_needs_owner",
            DomainEvent.aggregate_id == storyboard_id,
        )
        .order_by(DomainEvent.sequence)
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        index = payload.get("scene_number")
        if not isinstance(index, int):
            continue
        suggested = payload.get("suggested")
        if payload.get("failure_kind") != "SAFETY" or not isinstance(suggested, dict):
            moves.pop(index, None)
            continue
        moves[index] = {
            "model_id": suggested.get("model_id"),
            "credits": suggested.get("credits"),
            "status": suggested.get("status"),
            "reason_ro": suggested.get("reason_ro") or payload.get("reason"),
            "failure_kind": "SAFETY",
            "refused": payload.get("reason"),
        }
    return moves


#: What a redo plan shows on the sheet beside a scene's «Refă» button.
_REDO_FIELDS = (
    "plan_hash",
    "free",
    "buyable",
    "credits",
    "cap_credits",
    "cost_usd",
    "cap_usd",
    "model_id",
    "resolution",
    "price_source",
    "reason_ro",
    "replaces",
    "invalidates",
    # A still redo whose prompt the studio wrote again (old and new words), else None.
    "prompt_rewrite",
)


def _redo_view(plan: dict[str, Any]) -> dict[str, Any]:
    view = {name: plan.get(name) for name in _REDO_FIELDS}
    view["available"] = True
    return view


def _redo_plans(
    engine: Engine,
    storyboard_id: str,
    ctx: _Context,
    overrides: dict[int, str | None],
    kinds: dict[int, str],
) -> tuple[dict[int, dict[str, dict[str, Any]]], dict[str, Any]]:
    """Each scene's redo plans (still and motion for a filmed scene, card for a card) and
    the film's sound, each with the plan_hash his «Refă» answer is bound to.

    Computed exactly as the redo routes compute them (`redo_plan` with the same wiring), so
    the hash the drawer sends is the one `redo_scene` checks. 0 credits, no network.
    """

    def plan(kind: str, index: int | None) -> dict[str, Any]:
        try:
            return _redo_view(
                redo_plan(
                    engine,
                    storyboard_id,
                    kind,
                    index,
                    capabilities=list(ctx.capabilities),
                    integration_id=ctx.integration_id,
                    overrides=overrides,
                    resolution=ctx.resolution,
                    stills_model=ctx.stills_model,
                )
            )
        except SceneRedoRefused as exc:
            return {"available": False, "plan_hash": None, "reason_ro": exc.reason_ro}
        except (UnpricedError, ValueError) as exc:
            return {"available": False, "plan_hash": None, "reason_ro": str(exc)[:300]}

    per_scene: dict[int, dict[str, dict[str, Any]]] = {}
    for index, kind in kinds.items():
        names = ("card",) if kind in CARD_KINDS else ("still", "motion")
        per_scene[index] = {name: plan(name, index) for name in names}
    return per_scene, plan("audio", None)


def _catalogue_view(policy: dict[str, Any]) -> dict[str, Any]:
    """The Owner's three choices in config/film_models.json, as the planner read them."""
    try:
        catalogue = load_film_models()
    except ValueError as exc:
        return {
            "premium_model_id": None,
            "premium_resolution": None,
            "allowed_models": None,
            "hero_threshold": None,
            "catalogue_problem_ro": str(exc)[:300],
        }
    reference = policy.get("premium_reference") or {}
    return {
        "premium_model_id": reference.get("model_id") or catalogue.premium_reference[0],
        "premium_resolution": reference.get("resolution") or catalogue.premium_reference[1],
        "allowed_models": sorted(catalogue.allowed) if catalogue.allowed is not None else None,
        "hero_threshold": catalogue.hero_threshold,
        "catalogue_problem_ro": None,
    }


def _warm_shot_durations(takes: Iterable[SceneTake], *, workers: int = 4) -> None:
    """Measure independent local files concurrently; reuse the assembler's content cache."""
    unique = {
        take.sha256: take
        for take in takes
        if take.kind in SHOT_TAKE_KINDS and take.status in ("PAID", "APPROVED") and take.sha256
    }
    if not unique:
        return
    with ThreadPoolExecutor(max_workers=min(max(1, workers), len(unique))) as pool:
        list(pool.map(shot_clip_seconds, unique.values()))


def _sheet(
    engine: Engine,
    storyboard_id: str,
    ctx: _Context,
    *,
    account: Any = None,
    read_live: bool = True,
    include_redos: bool = True,
    face_counter: Callable[..., Any] | None = None,
    environment: str | None = None,
    settings: Any = None,
) -> dict[str, Any]:
    from app.factual.story_review import story_gate  # noqa: PLC0415
    from app.media.prompt_agent import motion_prompt_for, shot_plan_gaps  # noqa: PLC0415
    from app.media.qc import owner_local_moves  # noqa: PLC0415 - qc reads the sheet's events
    from app.media.renders_cap import cap_local_moves  # noqa: PLC0415 - it reads assembler
    from app.models import OwnerPolicy  # noqa: PLC0415
    from app.services import (  # noqa: PLC0415 - services imports media
        ACTION_RISK_TIERS,
        paid_media_policy,
        studio_environment,
    )

    environment = environment or studio_environment(engine)
    # The sources a scene's package may come from: the model's for a factual film, the
    # series look's too for the office serial (2026-10-11, f06808c9: the sheet counted the
    # serial's composed scenes as gaps and refused its walk NEEDS_SHOT_PLAN).
    sources = shot_plan_sources(engine, storyboard_id)

    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise SheetNotFound("Storyboard-ul nu există.")
        title = board.title
        story_passed, story_reason = story_gate(session, board.script_draft_id)
        bible = dict(board.visual_bible_json or {})
        rows = list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == storyboard_id)
                .order_by(StoryboardScene.scene_index)
            )
        )
        if not rows:
            raise SheetNotFound("Storyboard-ul nu are scene.")
        scenes = [scene_view(row) for row in rows]
        gaps = shot_plan_gaps(session, storyboard_id, sources)
        takes = _scene_takes(session, storyboard_id)
        # The takes his newest look approved as final (2026-10-11): shown on the sheet, and
        # the only ones the Director's confirmed repair leaves alone.
        final_ids = {
            take_id
            for take_id, said in owner_take_decisions(
                session, [t.id for rows_ in takes.values() for t in rows_]
            ).items()
            if said and said[-1].get("decision") == "APPROVED" and said[-1].get("final")
        }
        stills: dict[int, SceneTake] = {}
        for scene in scenes:
            index = int(scene["scene_index"])
            if scene_kind_of(scene) != "LIVE":
                continue
            # Looked for by the identity the assembly looks for: the words and the reference
            # picture of the character the scene shows (none of a locked one without it).
            found = usable_take(
                session,
                storyboard_id,
                index,
                "still",
                still_options(engine, scene),
                statuses=("APPROVED",),
            )
            if found is not None:
                stills[index] = found
        rule, threshold = paid_media_policy(session.get(OwnerPolicy, 1))
        # What the assemble step will find: per filmed scene, a shot it may cut in or the
        # Owner's own LOCAL_MOVE; and each shot's clip-QC report, for his look.
        # 2026-10-09 (babcf272): the sheet said «Pregătit» four times while the render refused
        # scene 3, its 5.0 s clip shorter than the 6.06 s of words it had to carry: the sheet
        # looked for a shot of any length. It now reads the render's own readiness
        # (`assembly_readiness`): the same shot identity, the same span from the narration
        # (measured, else estimated), the same slow-down allowance.
        # His own LOCAL_MOVE, and the Director's past his renders cap (a scene whose motion
        # had its renders and has no clip that carries it: its still moved locally).
        cap_moves = cap_local_moves(session, storyboard_id)
        local_moves = owner_local_moves(session, storyboard_id) | cap_moves
        if read_live and not include_redos:
            _warm_shot_durations(
                (take for scene_takes in takes.values() for take in scene_takes),
                workers=getattr(settings, "sheet_probe_workers", 4),
            )
        readiness = assembly_readiness(
            session,
            storyboard_id,
            scenes,
            {
                int(scene["scene_index"]): (
                    str(stills[int(scene["scene_index"])].sha256 or "") or None
                    if int(scene["scene_index"]) in stills
                    else None
                )
                for scene in scenes
                if scene_kind_of(scene) == "LIVE"
            },
            environment=environment,
            local_moves=local_moves,
            cap_moves=cap_moves,
        )
        # Each clip's length as the motion step buys it: the narration it will carry.
        sizes = clip_plan(session, storyboard_id, scenes)
        # The newest refused assembly, until a film is assembled (shown with its seconds).
        refusal = latest_assembly_refusal(session, storyboard_id)
        clip_reports = {
            take.id: clip_qc_of(session, take.id)
            for rows_ in takes.values()
            for take in rows_
            if take.kind in ("test_shot", "motion")
        }
        accepted_heroes = hero_acceptances(
            session,
            [take.id for rows_ in takes.values() for take in rows_ if take.kind == "test_shot"],
        )
        safety = _safety_moves(session, storyboard_id)
        narration = _narration(session, scenes, voiced_scenes(session, storyboard_id, scenes))
        session.expunge_all()

    overrides = sheet_overrides(engine, storyboard_id)
    seed = film_seed(storyboard_id)
    faces_forbidden = bible_face_rule(bible) is not None

    # The two steps' own plans: what each would buy now, its cost and its cap.
    try:
        stills_step = stills_plan(engine, storyboard_id, model_id=ctx.stills_model, table=ctx.table)
    except UnpricedError as exc:
        # A still with no published price is never bought on a guess: the step shows nothing
        # to buy and says why.
        stills_step = {
            "model_id": ctx.stills_model,
            "ratio": None,
            "candidates": STILL_CANDIDATES,
            "max_rerolls": 0,
            "to_buy": [],
            "held": [],
            "needs_reference": [],
            "scenes": [],
            "unpriced_ro": f"Imaginile nu au preț: {exc}.",
        }
    # Per scene, why its still is not bought: left to the Owner by an earlier step, or a
    # locked character with no reference picture (stills_plan's own reading).
    still_holds = {
        int(entry["scene_index"]): {"status": entry["status"], "reason_ro": entry["reason_ro"]}
        for entry in stills_step.get("scenes") or []
        if entry.get("status") in ("NEEDS_OWNER", "NEEDS_REFERENCE")
    }
    moving = motion_plan(
        engine,
        storyboard_id,
        capabilities=list(ctx.capabilities),
        allowed=ctx.allowed,
        overrides=overrides,
        resolution=ctx.resolution,
        table=ctx.table,
    )
    moving_view = {int(item["scene_index"]): item for item in moving["scenes"]}
    bought = {
        index: str(item["model_id"])
        for index, item in moving_view.items()
        if item["status"] == "BOUGHT" and item.get("model_id")
    }

    # The whole film's per-scene choice, priced even before its stills exist: the Owner sees
    # every scene's model and price before the first credit, not only after the stills.
    # Each clip at the length its narration needs (`clip_plan`, the motion step's own), so
    # the price he reads is the price of the clip that will be bought.
    def shot_seconds(scene: dict[str, Any]) -> float:
        entry = sizes.get(int(scene["scene_index"]))
        return float(entry["seconds"]) if entry is not None else motion_seconds(scene)

    needs = [
        need_from_scene({**scene, "duration_seconds": shot_seconds(scene)}, len(scenes))
        for scene in scenes
    ]
    policy = plan_scene_models(
        needs,
        list(ctx.capabilities),
        allowed=ctx.allowed,
        overrides=overrides,
        keep=bought,
        bought=list(bought),
        resolution=ctx.resolution,
        table=ctx.table,
        today=ctx.today,
    )
    chosen = {int(entry["scene_index"]): entry for entry in policy["scenes"]}
    # The ready-to-buy plan clears prices while stills are missing. The read-only hero
    # preview needs the same future quotes shown on this sheet, without making shots ready.
    hero_preview = {
        **moving,
        "hero_scene": moving["hero_scene"]
        if moving["hero_scene"] is not None
        else policy["hero_scene"],
        "scenes": [
            {**item, "credits": int(chosen[item["scene_index"]].get("credits") or 0)}
            if item["status"] == "NEEDS_STILL"
            else item
            for item in moving["scenes"]
        ],
    }
    with Session(engine) as session:
        hero = hero_gate(
            session, hero_preview, storyboard_id=storyboard_id, plan_hash=moving["plan_hash"]
        )
    try:
        stills_row: PriceRow | None = ctx.table.row(ctx.stills_model, STILLS_RESOLUTION)
    except UnpricedError:
        stills_row = None
    still_label = source_label(stills_row, today=ctx.today) if stills_row else "fără preț"

    lint_scenes: list[LintScene] = []
    sheet_scenes: list[dict[str, Any]] = []
    hashed_scenes: list[dict[str, Any]] = []
    for scene in scenes:
        index = int(scene["scene_index"])
        kind = scene_kind_of(scene)
        package = scene.get("prompt_json") or {}
        entry = chosen.get(index, {})
        model_id = entry.get("model_id") or (entry.get("suggested") or {}).get("model_id")
        still_text = ""
        motion_text = ""
        negative: str | None = None
        if kind == "LIVE":
            still_text = str(package.get("still_prompt") or scene.get("visual_prompt") or "")
            if package.get("prompt_format") != "editor_final_v1":
                still_text = " ".join(still_text.split())
            motion_text, negative = motion_prompt_for(package, model_id, None)
        from app.media.prompt_agent import composition_issues  # noqa: PLC0415

        still = stills.get(index)
        lint_scenes.append(
            LintScene(
                scene=index,
                kind=kind,
                still_prompt=still_text,
                motion_prompt=motion_text,
                model_id=entry.get("model_id") if kind == "LIVE" else None,
                contract={"still_model_id": ctx.stills_model, "model_id": model_id},
                composition_issues=tuple(
                    composition_issues(
                        package,
                        still_text,
                        motion_text,
                        layers=("motion",) if still is not None else ("still", "motion"),
                    )
                )
                if kind == "LIVE" and package.get("prompt_format") != "editor_final_v1"
                else (),
            )
        )
        view = moving_view.get(index, {})
        motion = {
            key: entry.get(key)
            for key in (
                "model_id",
                "status",
                "tier",
                "decided_by",
                "reason_ro",
                "resolution",
                "billed_seconds",
                "credits",
                "usd_micros",
                "price_source",
                "quality",
                "required_quality",
                "cheaper",
                "better",
                "suggested",
                "warnings_ro",
                "excluded",
                # A clip bought at the model's longest and slowed at assembly, or a scene no
                # clip carries even slowed (`production_policy._choose_scene`).
                "slowed",
                "too_long",
            )
        }
        motion["seed"] = seed if kind == "LIVE" else None
        motion["usd"] = round(int(entry.get("usd_micros") or 0) / 1_000_000, 6)
        motion["step_status"] = view.get("status")
        motion["take_id"] = view.get("take_id")
        motion["take_kind"] = view.get("take_kind")
        motion["take_status"] = view.get("take_status")
        motion["accepted_by"] = view.get("accepted_by")
        card: dict[str, Any] | None = None
        if kind in CARD_KINDS:
            problem = None
            try:
                card_spec_from_json(kind, scene.get("card_json"))
            except CardError as exc:
                problem = str(exc)
            card = {
                "card_json": scene.get("card_json"),
                "problem_ro": problem,
                "preview_url": (
                    f"/api/v1/media/storyboards/{storyboard_id}/scenes/{index}/card-preview"
                ),
                "provenance": "composed",
                "credits": 0,
            }
        candidates = [
            _take_view(
                take,
                current=take.prompt_hash == still.prompt_hash if still else False,
                final=take.id in final_ids,
            )
            for take in takes.get(index, [])
            if take.kind == "still" and (still is None or take.id != still.id)
        ]
        shots = [
            _take_view(
                take,
                current=True,
                clip_qc=clip_reports.get(take.id),
                accepted_by=HERO_ACCEPTED_BY if take.id in accepted_heroes else None,
                final=take.id in final_ids,
            )
            for take in takes.get(index, [])
            if take.kind in ("test_shot", "motion")
        ]
        motion["safety_suggested"] = (
            safety.get(index) if kind == "LIVE" and view.get("status") != "BOUGHT" else None
        )
        sheet_scenes.append(
            {
                "scene_index": index,
                "kind": kind,
                "story_purpose": scene.get("story_purpose"),
                "narration": scene.get("voiceover_segment"),
                "planned_seconds": float(scene.get("duration_seconds") or 0.0),
                "shot_seconds": shot_seconds(scene) if kind == "LIVE" else 0.0,
                # Where the clip's length comes from: "planned", or the narration
                # "rendered" / "measured" / "estimated" (`clip_plan`), and its words' seconds.
                "shot_seconds_source": (sizes.get(index) or {}).get("source"),
                "spoken_seconds": (sizes.get(index) or {}).get("spoken_seconds"),
                "prompt_source": package.get("source"),
                "shot_size": package.get("shot_size"),
                "still_prompt": still_text,
                "motion_prompt": motion_text,
                "negative_prompt": negative,
                "still": (
                    {
                        "take_id": still.id,
                        "sha256": still.sha256,
                        "approved_by": still.approved_by,
                        "owner_final": still.id in final_ids,
                        "model_id": still.model_id,
                        "file_url": _file_url(still.id),
                    }
                    if still is not None
                    else None
                ),
                "candidates": candidates,
                "shots": shots,
                "card": card,
                "override": overrides.get(index),
                "motion": motion,
                "still_hold": still_holds.get(index),
                "still_credits": int(entry.get("still_credits") or 0) if kind == "LIVE" else 0,
                "still_price_source": still_label if kind == "LIVE" else None,
                "price_line_ro": _price_line(kind, motion, ctx.table.credit_usd),
                "lint": [],
                "badges": [],
                "redo": {},
                "_still_path": still.path if still is not None else None,
                "_look": str(package.get("look_block") or ""),
            }
        )
        hashed_scenes.append(
            {
                "scene_index": index,
                "kind": kind,
                "card_json": scene.get("card_json") if kind in CARD_KINDS else None,
                "still_prompt": still_text,
                "motion_prompt": motion_text,
                "negative_prompt": negative,
                "still_sha256": still.sha256 if still is not None else None,
                "model_id": entry.get("model_id"),
                "status": entry.get("status"),
                "decided_by": entry.get("decided_by"),
                "override": overrides.get(index),
                "billed_seconds": entry.get("billed_seconds"),
                "credits": entry.get("credits"),
                "still_credits": entry.get("still_credits"),
                "take_id": view.get("take_id"),
                "take_status": view.get("take_status"),
                # Who accepted the hero (the Owner, or its clip QC under his rule): a new
                # acceptance is a new sheet.
                "accepted_by": view.get("accepted_by"),
            }
        )

    findings = lint_film(lint_scenes, bible=bible)
    # 2026-10-10 (film 6fe6a577): a scene no clip of its model carries, even slowed down
    # locally, held only itself for the Owner while the steps would buy the film's stills,
    # test shot and other clips, and the assembly could never cut it. It now blocks the whole
    # sheet before anything is bought, like a prompt BLOCK: the staircase refuses LINT_BLOCKED
    # (HELD, not his question), and the sheet's issue scan hands it to the Director, whose
    # repair rewrites the story with the scene split (`sheet_story_repair`).
    findings += [
        Finding(
            code=SCENE_TOO_LONG,
            severity=BLOCK,
            scene=index,
            evidence=f"{entry['too_long']['seconds']} s",
            message_ro=str(entry["too_long"]["reason_ro"]),
        )
        for index, entry in sorted(chosen.items())
        if entry.get("too_long")
    ]
    per_scene: dict[int, list[dict[str, Any]]] = {}
    for finding in findings:
        if finding.scene is not None:
            per_scene.setdefault(int(finding.scene), []).append(finding.as_dict())
    for item in sheet_scenes:
        item["lint"] = per_scene.get(item["scene_index"], [])
        still_path = item.pop("_still_path")
        look = item.pop("_look")
        if item["kind"] == "LIVE":
            item["badges"] = _badges(
                still_prompt=item["still_prompt"],
                look_block=look or item["still_prompt"],
                faces_forbidden=faces_forbidden,
                still_path=still_path if read_live else None,
                face_findings=any(
                    f["code"] in ("FORBIDDEN_FACES", "BIBLE_RULE_MISSING") for f in item["lint"]
                ),
                face_counter=face_counter,
            )

    # Who is buying for the film right now (never part of the hash: a step being bought does
    # not change what is bought). The page disables the buy buttons with its reason.
    lease = current_lease(engine, storyboard_id)

    def step_view(name: str, plan: dict[str, Any], waiting_ro: str) -> dict[str, Any]:
        action = SHEET_STEP_ACTIONS[name]
        to_buy = [int(index) for index in plan.get("to_buy") or []]
        return {
            "step": name,
            "action": action,
            "tier": ACTION_RISK_TIERS.get(action),
            "to_buy": to_buy,
            "cost_credits": int(plan.get("cost_credits") or 0),
            "cap_credits": int(plan.get("cap_credits") or 0),
            "cost_usd": float(plan.get("cost_usd") or 0.0),
            "cap_usd": float(plan.get("cap_usd") or 0.0),
            "ready": bool(to_buy),
            "waiting_ro": "" if to_buy else waiting_ro,
            # Scenes of this step a bought stair left to the Owner: never bought again until
            # he decides on the sheet (assembler.scene_memory).
            "held": [int(index) for index in plan.get("held") or []],
            "in_progress": bool(lease and lease["step"] in (name, "staircase")),
            # RunPod Serverless: what one GPU start of a round adds (cold start + idle tail),
            # already inside the cost and the cap; the Owner reads it as its own line.
            "gpu_start_credits": int(plan.get("round_overhead_credits") or 0),
            "gpu_start_ro": (
                f"{OVERHEAD_LINE_RO}: {_ro_credits(int(plan['round_overhead_credits']))} pe rundă"
                if plan.get("round_overhead_credits")
                else ""
            ),
        }

    needs_reference = list(stills_step.get("needs_reference") or [])
    if needs_reference:
        stills_waiting = needs_reference_reason(needs_reference)
    elif stills_step.get("held"):
        stills_waiting = " ".join(
            str(still_holds[index]["reason_ro"])
            for index in stills_step["held"]
            if index in still_holds
        )
    else:
        stills_waiting = "Toate imaginile scenelor filmate sunt deja aprobate; nu se cumpără nimic."
    steps = {
        STILLS_STEP: {
            **step_view(STILLS_STEP, stills_step, stills_waiting),
            "needs_reference": needs_reference,
            "model_id": stills_step["model_id"],
            "ratio": stills_step["ratio"],
            "candidates": stills_step["candidates"],
            "max_rerolls": stills_step["max_rerolls"],
            "price_source": still_label,
        },
        TEST_SHOT_STEP: step_view(
            TEST_SHOT_STEP,
            moving["steps"][TEST_SHOT_STEP],
            "Cadrul de probă se cumpără după ce imaginea scenei lui este aprobată "
            "(sau a fost deja cumpărat).",
        ),
        MOTION_STEP: {
            **step_view(
                MOTION_STEP,
                moving["steps"][MOTION_STEP],
                "Restul mișcării se cumpără după ce imaginile sunt aprobate și cadrul de probă "
                "este acceptat: de controlul clipului, cum permite regula ta pentru pașii "
                "plătiți, sau de Proprietar pe foaia de filmare."
                if hero["rule_accepts"]
                else "Restul mișcării se cumpără după ce imaginile sunt aprobate și Proprietarul "
                "a aprobat cadrul de probă.",
            ),
            # The hero gate in the Owner's words: who accepted the test shot, or what it waits
            # for (his look, its clip QC, or a refusal above both).
            "hero": hero,
        },
    }
    if steps[MOTION_STEP]["to_buy"] and hero["status"] in ("NOT_BOUGHT", "WAITING", "REFUSED"):
        # Shots are planned, but the step would refuse before buying them: say why.
        steps[MOTION_STEP]["waiting_ro"] = hero["reason_ro"]
    blocked = [
        {
            **item,
            # A clip too short for its words says so once, in its own sentence (reason_ro
            # carries why_ro and the way out), never twice (`blocked_words`).
            "why_ro": "" if item.get("code") == CLIP_SHORT else item.get("why_ro") or "",
        }
        for item in readiness
        if not item["ok"]
    ]
    paid_left = [name for name in SHEET_STEPS if steps[name]["to_buy"]]
    steps[ASSEMBLE_STEP] = {
        "step": ASSEMBLE_STEP,
        "action": NARRATION_ACTION,
        "tier": ACTION_RISK_TIERS.get(NARRATION_ACTION),
        "environment": environment,
        "ready": not blocked,
        "blocked": [
            {
                "scene_index": item["scene_index"],
                "reason_ro": item["reason_ro"],
                "code": item.get("code"),
                "why_ro": item.get("why_ro") or "",
                # A clip too short for its span: its seconds and what its redo must reach.
                "clip_seconds": item.get("clip_seconds"),
                "span": item.get("span"),
                "needed_seconds": item.get("needed_seconds"),
            }
            for item in blocked
        ],
        # What the assembly will do of its own, at 0 USD, said before he presses: the clips
        # it slows into their spans, and the clips whose words are not measured yet and may
        # be too short once they are ("at_risk", `clip_readiness`: never a slow-down promised
        # past the 25% allowance; a clip too short even for the shortest reading is blocked).
        "notes_ro": [
            text
            for item in readiness
            if item["ok"]
            for text in (
                item.get("reason_ro") if item.get("how") == "slowed" else "",
                item.get("risk_ro") or "",
            )
            if text
        ],
        # The newest refused assembly (ASSEMBLY_REFUSED_EVENT), until a film is assembled.
        "last_refusal": (
            {
                "at": refusal.get("at"),
                "stage": refusal.get("stage"),
                "reason_ro": refusal.get("reason_ro"),
                "scenes": refusal.get("scenes") or [],
            }
            if refusal is not None
            else None
        ),
        # The wait said once, the scenes grouped (2026-10-04: one sentence per scene, x5).
        "blocked_ro": blocked_words(blocked),
        "scenes": readiness,
        "paid_steps_left": paid_left,
        "narration": narration,
        "cost_usd": narration["usd"],
        "cost_credits": 0,
        "cap_credits": 0,
        "waiting_ro": blocked_words(blocked),
        "in_progress": bool(lease and lease["step"] in (ASSEMBLE_STEP, "staircase")),
    }

    hashed = {
        "storyboard_id": storyboard_id,
        "resolution": ctx.resolution,
        "seed": seed,
        "stills": {
            "model_id": ctx.stills_model,
            "resolution": STILLS_RESOLUTION,
            "candidates": STILL_CANDIDATES,
        },
        "scenes": hashed_scenes,
        "steps": {
            name: {
                "to_buy": step["to_buy"],
                "cost": step["cost_credits"],
                "cap": step["cap_credits"],
            }
            for name, step in steps.items()
            if name in SHEET_STEPS
        },
        "hero_scene": policy.get("hero_scene"),
        # The narration is a paid line of the plan the Owner approves: new words or a new
        # price is a new sheet.
        "narration": {
            "characters": narration["characters"],
            "usd_micros": narration["usd_micros"],
            "priced": narration["priced"],
        },
    }
    digest = hashlib.sha256(_canonical(hashed).encode("utf-8")).hexdigest()

    # Every price the sheet uses, each with where it comes from.
    used: list[tuple[PriceRow, str]] = (
        [(stills_row, STILLS_RESOLUTION)] if stills_row is not None else []
    )
    seen: set[tuple[str, str]] = set()
    for entry in policy["scenes"]:
        if not (entry.get("model_id") and entry.get("resolution")):
            continue
        key = (str(entry["model_id"]), str(entry["resolution"]))
        if key in seen:
            continue
        seen.add(key)
        try:
            used.append((ctx.table.row(*key), key[1]))
        except UnpricedError:
            continue
    used_rows = [row for row, _resolution in used]
    prices = [
        {
            "model_id": row.model_id,
            "kind": row.kind,
            "resolution": resolution,
            "credits_per_second": row.credits_per_second,
            "credits_per_image": row.credits_per_image,
            "minimum_credits": row.minimum_credits,
            "provenance": row.provenance,
            "date": row.date,
            "source_url": row.source_url,
            "source": source_label(row, today=ctx.today),
        }
        for row, resolution in used
    ]

    credit_usd = ctx.table.credit_usd

    def usd(credits: int) -> int:
        return credits_to_micros(int(credits), credit_usd)

    balance = (
        _read_balance(account)
        if read_live
        else {"credits": None, "read": False, "problem": "necitit"}
    )
    blocks = [finding for finding in findings if finding.severity == BLOCK]
    margin = margin_of(settings)
    footer = {
        "stills_spent_credits": _stills_spent(takes),
        "stills_to_buy_credits": steps[STILLS_STEP]["cost_credits"],
        "stills_to_buy_usd_micros": usd(steps[STILLS_STEP]["cost_credits"]),
        "stills_credits": int(policy["stills_credits"]),
        "hero_scene": policy.get("hero_scene"),
        "hero_credits": int(policy["hero_credits"]),
        "hero_usd_micros": usd(policy["hero_credits"]),
        "rest_credits": int(policy["rest_credits"]),
        "rest_usd_micros": usd(policy["rest_credits"]),
        "motion_credits": int(policy["motion_credits"]),
        "total_credits": int(policy["total_credits"]),
        "total_usd_micros": usd(policy["total_credits"]),
        "cap_credits": int(policy["cap_credits"]),
        "cap_usd_micros": usd(policy["cap_credits"]),
        "premium_credits": int(policy["premium_credits"]),
        "saved_credits": int(policy["saved_credits"]),
        "saved_usd_micros": usd(policy["saved_credits"]),
        "price_source": _source_of(used_rows, ctx.today),
        "summary_ro": policy.get("summary_ro"),
        "alternatives": _alternatives(policy, ctx, stills_row),
        "balance": balance,
        "runpod_metrics": _runpod_metrics(engine, storyboard_id),
        # What the balance must hold to START each paid step: its next round x the margin
        # (the Owner's rule of 2026-10-03); its cap stays the ceiling, said beside it.
        "balance_needed_credits": {
            name: needed_credits(steps[name]["cost_credits"], margin) for name in SHEET_STEPS
        },
        "balance_rule": {
            name: {
                "round_credits": int(steps[name]["cost_credits"]),
                "cap_credits": int(steps[name]["cap_credits"]),
                "needed_credits": needed_credits(steps[name]["cost_credits"], margin),
                "margin": margin,
                "line_ro": round_line_ro(
                    steps[name]["cost_credits"], steps[name]["cap_credits"], margin
                ),
            }
            for name in SHEET_STEPS
        },
        "daily_budget": _daily_budget(engine) if read_live else None,
        # The film's own ceiling (PRODUCTION): its limit, what the books hold for it, the rest.
        "film_budget": film_budget_view(engine, storyboard_id, settings, ctx.table),
        "narration": narration,
        **_catalogue_view(policy),
        "audio_redo": None,
        "sheet_hash": digest,
    }
    if read_live and include_redos:
        # The «Refă» buttons' plans, each with its own hash: only on the page the Owner
        # reads (a step's own check of the sheet's hash does not need them).
        redo_by_scene, audio = _redo_plans(
            engine,
            storyboard_id,
            ctx,
            overrides,
            {int(item["scene_index"]): str(item["kind"]) for item in sheet_scenes},
        )
        for item in sheet_scenes:
            item["redo"] = redo_by_scene.get(int(item["scene_index"]), {})
        footer["audio_redo"] = audio
    elif read_live:
        # Quote only the redo the Owner opens, through the existing redo-plan route.
        # Computing every motion redo recalculates the whole film once per scene.
        for item in sheet_scenes:
            names = ("card",) if item["kind"] in CARD_KINDS else ("still", "motion")
            item["redo"] = {name: {"deferred": True} for name in names}
        footer["audio_redo"] = {"deferred": True}
    return {
        "storyboard_id": storyboard_id,
        "title": title,
        "sheet_hash": digest,
        "seed": seed,
        "resolution": ctx.resolution,
        "credit_usd": credit_usd,
        "faces_forbidden": faces_forbidden,
        "owner_rule": {"paid_media_approval": rule, "over_usd": threshold},
        "shot_plan_gaps": gaps,
        "story_review": {"passed": story_passed, "reason": story_reason},
        "reference_images_verified": _reference_verified(),
        "scenes": sheet_scenes,
        "lint": [finding.as_dict() for finding in findings],
        "blocks": [finding.as_dict() for finding in blocks],
        "lint_blocked": has_block(findings),
        "lint_summary_ro": summary_ro(findings) if findings else "",
        "steps": steps,
        "prices": prices,
        "footer": footer,
        "in_progress": ({**lease, "reason_ro": _busy_reason(lease)} if lease is not None else None),
    }


def _runpod_metrics(engine: Engine, storyboard_id: str) -> dict[str, Any] | None:
    from app.media.models import VideoRenderJob  # noqa: PLC0415
    from app.providers.runpod.telemetry import generation_metrics  # noqa: PLC0415

    with Session(engine) as session:
        finished = session.scalar(
            select(VideoRenderJob.id).where(
                VideoRenderJob.storyboard_id == storyboard_id, VideoRenderJob.status == "COMPLETED"
            )
        )
    result = generation_metrics(engine, storyboard_id, finished=finished is not None)
    return result if result["jobs"] else None


def _reference_verified() -> bool:
    """Whether Runway's referenceImages has been seen to work on this account. Until the
    first approved use proves it, the sheet says it is unverified."""
    from app.providers.runway import RunwayImageAdapter  # noqa: PLC0415

    return bool(getattr(RunwayImageAdapter, "REFERENCE_IMAGE_VERIFIED", False))


def build_sheet(
    engine: Engine,
    storyboard_id: str,
    *,
    capabilities: Iterable[ModelCapability] | None = None,
    integration_id: str | None = None,
    table: PriceTable | None = None,
    account: Any = None,
    allowed: Iterable[str] | None = None,
    resolution: str | None = None,
    stills_model: str | None = None,
    today: date | None = None,
    face_counter: Callable[..., Any] | None = None,
    read_live: bool = True,
    include_redos: bool = True,
    environment: str | None = None,
    settings: Any = None,
) -> dict[str, Any]:
    """The shooting sheet of one film. 0 credits; the only live call is ``account``'s free
    balance read (and the local face count of each approved still, with ``face_counter``).

    ``capabilities`` are the motion models the per-scene choice draws from; the price table
    is the published one with ``integration_id``'s MEASURED prices laid over it.
    ``environment`` (default: the studio's) decides what the assemble step accepts.
    ``read_live`` also adds each scene's redo plans (the «Refă» buttons) to the page.
    With ``include_redos=False`` those quotes are deferred to the individual redo-plan GET;
    prices, validation and the sheet hash used by purchase gates are unchanged.
    """
    from app.media.factory import reference_model_for_storyboard  # noqa: PLC0415

    stills_model = reference_model_for_storyboard(engine, storyboard_id, stills_model)
    ctx = _context(
        engine,
        capabilities=capabilities,
        integration_id=integration_id,
        table=table,
        allowed=allowed,
        resolution=resolution,
        stills_model=stills_model,
        today=today,
    )
    return _sheet(
        engine,
        storyboard_id,
        ctx,
        account=account,
        read_live=read_live,
        include_redos=include_redos,
        face_counter=face_counter,
        environment=environment,
        settings=settings,
    )


def sheet_hash(engine: Engine, storyboard_id: str, **context: Any) -> str:
    """The sheet's hash alone: no balance read, no face count."""
    context.pop("account", None)
    context.pop("face_counter", None)
    context["read_live"] = False
    digest: str = build_sheet(engine, storyboard_id, **context)["sheet_hash"]
    return digest


# ------------------------------------------------------------------------- the steps


def may_spend_step(engine: Engine, cap_usd_micros: int) -> tuple[str, str] | None:
    """(period, Romanian reason) when a paid step's cap would exceed an active budget;
    None when every budget allows it. The check of every paid step of a film: the sheet's
    steps, the assemble step's narration and a one-scene redo."""
    from app.economy.budget import may_spend  # noqa: PLC0415 - economy imports media
    from app.economy.services import format_micros  # noqa: PLC0415

    verdict = may_spend(engine, cap_usd_micros)
    if verdict["allowed"]:
        return None
    period = str(verdict.get("period") or "DAILY")
    detail = next(
        (p for p in verdict["status"]["budgets"] if p["period"] == period),
        None,
    )
    word = PERIOD_WORDS.get(period, period.lower())
    if detail is None:
        return period, f"Bugetul {word} ar fi depășit."
    return period, (
        f"Bugetul {word} de {detail['limit_usd']} USD ar fi depășit: plafonul pasului este "
        f"{format_micros(cap_usd_micros)} USD și au rămas {detail['remaining_usd']} USD. "
        "Confirmați explicit depășirea pe foaia de filmare, sau așteptați perioada următoare."
    )


# ------------------------------------------------------------ the gates before every purchase
#
# 2026-10-02 (GATES_BEFORE_BUYING). Nothing is bought unless every gate passes, in this order:
# the film's purchase lease (one buyer per film, MONEY-04), the balance, the film's own
# ceiling (PRODUCTION, MONEY-07) against the step's whole cap, a hold of the step's next round
# against the budgets (AR-03: a reservation decided behind the write lock, not a reading;
# grown before each later round since 2026-10-16, `StepHold`), and then the Owner's rule in
# `may_act` (which refuses unasked buying in PRODUCTION with no daily budget, MONEY-06).

#: A second buyer of a film while the first is still buying (409; the day WAITs).
FILM_BUSY = "FILM_BUSY"
#: A step whose cap would take the film past its ceiling (409; the Owner may consent).
OVER_FILM_BUDGET = "OVER_FILM_BUDGET"
#: The Owner's consent to go past the film's ceiling for one step.
FILM_EXCESS_EVENT = "media.film_budget_excess_approved"
#: The Owner's consent to go past a period budget for one step.
BUDGET_EXCESS_EVENT = "media.budget_excess_approved"
#: A step's next round the budgets could not hold (its first, or a re-roll round): what it
#: needed and the period that refused it. `passes.day_goal` reads it as the day's budget spent
#: while that period has less left than the round needed.
STEP_HOLD_REFUSED_EVENT = "media.step_hold_refused"
#: What a lease is held for, in the Owner's words.
LEASE_WORDS_RO: dict[str, str] = {
    STILLS_STEP: "pasul «imaginile»",
    TEST_SHOT_STEP: "pasul «cadrul de probă»",
    MOTION_STEP: "pasul «restul mișcării»",
    ASSEMBLE_STEP: "asamblarea",
    "scene_redo": "o refacere de scenă",
    "staircase": "rularea zilei",
    "close": "închiderea filmului",
    "story_repair": "remedierea poveștii foii",
    "prompt_repair": "remedierea prompturilor foii",
}
#: The lease step of the Owner's «Închide filmul» (`film_close.close_film`): it holds the film
#: while it closes, so no purchase of it can start or be running meanwhile. It is the one step
#: a closed film's lease is still taken for: every other holder (a purchase, the day's
#: staircase and assembly, a redo, the sheet's story and prompt repairs, which would write a
#: replacement storyboard or reopen the film as NEEDS_SHOT_PLAN) meets `FilmClosed`.
CLOSE_LEASE_STEP = "close"
#: A purchase refused because the film is closed (409; the day skips the film).
FILM_CLOSED = "FILM_CLOSED"
FILM_CLOSED_RO = (
    "Filmul este închis: pentru el nu se mai cumpără nimic și nu ți se mai cere nimic. Ce s-a "
    "cumpărat pentru el rămâne în registre."
)
#: How long a lease stands when the settings do not say (STUDIO_FILM_PURCHASE_LEASE_SECONDS).
#: The ceiling of one purchase's hold: its holder renews it up to this, never beyond.
DEFAULT_LEASE_SECONDS = 10_800
#: A held lease is renewed this often by its holder's process (`_LeaseKeeper`) ...
LEASE_RENEW_SECONDS = 60.0
#: ... and never stands further ahead than this: a holder that is gone (the studio restarted,
#: or crashed) stops renewing, and its lease lapses within these few minutes instead of the
#: three hours it once stood (2026-10-03: the Owner's film refused every press «acum 144 de
#: minute» for a redo whose process had been stopped two hours before).
LEASE_STALE_SECONDS = 300
#: The event of a lease taken back from a holder that is gone, with what it had done.
LEASE_RECLAIMED_EVENT = "media.film_purchase_lease_reclaimed"
#: The kind of the Owner's letter about it.
ABANDONED_LETTER_KIND = "film_purchase_abandoned"
#: The film ceiling's default stills allowance: the stills cap of a six-scene film.
DEFAULT_CEILING_SCENES = 6


class FilmBusy(RuntimeError):
    """Another buyer holds this film's purchase lease; nothing was bought here."""

    def __init__(self, reason_ro: str, lease: dict[str, Any]) -> None:
        super().__init__(reason_ro)
        self.status = FILM_BUSY
        self.reason_ro = reason_ro
        self.lease = lease


class FilmClosed(FilmBusy):
    """The film is closed (`film_is_closed`): no purchase of it starts; nothing was bought.

    A FilmBusy, so every buyer that already stops on a busy film (a press, a redo, the day's
    staircase, FILM_CONTINUE) stops on a closed one as well, before anything is priced or
    asked; each says which by ``status`` (FILM_CLOSED)."""

    def __init__(self, storyboard_id: str) -> None:
        super().__init__(FILM_CLOSED_RO, {"storyboard_id": storyboard_id})
        self.status = FILM_CLOSED


def film_is_closed(session: Session, storyboard_id: str) -> bool:
    """Whether no further production is allowed: confirmed upload or closed unrendered film.

    That is a film the Owner closed («Închide filmul»), one the Director retired after it stood
    still, or one a newer storyboard of its script replaced; and a serial film that is its
    day's second, or whose episode is no longer approved (`story.duplicates`). A REJECTED film
    that has a finished render is a viewing the Director refused: its redos are the way back
    to a film, so it is not closed here. A render already uploaded to a channel is final for
    production, even when its storyboard still says APPROVED/RENDERED; privacy/metadata work
    stays separate.
    Match the immutable render asset, never a title that may have changed for publication."""
    from app.media.models import VideoRenderJob  # noqa: PLC0415
    from app.publishing.models import PublicationRecord  # noqa: PLC0415

    board = session.get(Storyboard, storyboard_id)
    if board is None:
        return False
    uploaded = session.scalar(
        select(PublicationRecord.id)
        .join(VideoRenderJob, VideoRenderJob.output_asset_id == PublicationRecord.media_asset_id)
        .where(
            VideoRenderJob.storyboard_id == storyboard_id,
            VideoRenderJob.status == "COMPLETED",
            PublicationRecord.status.in_(("PUBLISHED", "SCHEDULED", "REMOTE_CONFIRMED")),
            PublicationRecord.remote_video_id.is_not(None),
            PublicationRecord.remote_video_id != "",
        )
        .limit(1)
    )
    if uploaded is not None:
        return True
    from app.story.duplicates import serial_film_superseded  # noqa: PLC0415 - story imports us

    if serial_film_superseded(session, storyboard_id):
        # A serial day's second film, or one whose episode is no longer approved (2026-10-17):
        # nothing is bought for it (a7db1594 beside 87c05891, the same day of the serial).
        return True
    if board.status != "REJECTED":
        return False
    rendered = session.scalar(
        select(VideoRenderJob.id)
        .where(VideoRenderJob.storyboard_id == storyboard_id, VideoRenderJob.status == "COMPLETED")
        .limit(1)
    )
    return rendered is None


class PurchaseGateRefused(RuntimeError):
    """A gate before a purchase refused it (a budget, the film's ceiling); each caller says it
    in its own refusal (`SheetStepRefused`, `SceneRedoRefused`). Nothing was bought."""

    def __init__(self, status: str, reason_ro: str) -> None:
        super().__init__(reason_ro)
        self.status = status
        self.reason_ro = reason_ro


def _now() -> datetime:
    return datetime.now(UTC)


def _lease_view(row: FilmPurchaseLease) -> dict[str, Any]:
    return {
        "storyboard_id": row.storyboard_id,
        "holder": row.holder,
        "step": row.step,
        "acquired_at": row.acquired_at,
        "expires_at": row.expires_at,
    }


def _busy_reason(lease: dict[str, Any]) -> str:
    """«Filmul este deja în lucru: …» with what is being bought and for how long."""
    what = LEASE_WORDS_RO.get(str(lease.get("step")), "un pas plătit")
    try:
        started = datetime.fromisoformat(str(lease["acquired_at"]))
        minutes = max(0, int((_now() - started).total_seconds() // 60))
        since = f"a început acum {count_ro(minutes, 'minut', 'minute')}"
    except (KeyError, ValueError, TypeError):
        since = "a început mai devreme"
    return (
        f"Filmul este deja în lucru: {what} {since} și nu s-a terminat. Nu se cumpără nimic de "
        "două ori; foaia de filmare se reîncarcă singură când pasul se termină."
    )


#: The film leases whose holder is alive in THIS process: (storyboard_id, holder) while its
#: keeper renews it. A row that lapsed while its holder here still runs (the machine slept,
#: the clock jumped, a write lock stood past the window) is not a holder that is gone: the
#: watchdog of this process does not reclaim it and a second press here does not take it.
#: Another process's holders are known only by their renewals.
_LIVE_HOLDERS: set[tuple[str, str]] = set()
_LIVE_HOLDERS_LOCK = threading.Lock()


def _alive_here(storyboard_id: str, holder: str) -> bool:
    with _LIVE_HOLDERS_LOCK:
        return (storyboard_id, holder) in _LIVE_HOLDERS


def current_lease(engine: Engine, storyboard_id: str) -> dict[str, Any] | None:
    """Who is buying for this film now, or None (an expired lease is nobody's, unless its
    holder is still alive in this process)."""
    with Session(engine) as session:
        row = session.get(FilmPurchaseLease, storyboard_id)
        if row is None:
            return None
        if row.expires_at <= _now().isoformat() and not _alive_here(storyboard_id, row.holder):
            return None
        return _lease_view(row)


def held_films(engine: Engine) -> list[str]:
    """The films whose purchase lease is held now (`current_lease` for each row): their paid
    tasks belong to the buyer at work, who collects them itself."""
    with Session(engine) as session:
        films = list(session.scalars(select(FilmPurchaseLease.storyboard_id)).all())
    return [film for film in films if current_lease(engine, film) is not None]


@contextmanager
def film_purchase_lease(
    engine: Engine,
    storyboard_id: str,
    *,
    holder: str,
    step: str,
    ttl_seconds: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Hold this film's purchase lease while the block runs; `FilmBusy` when another holds it.

    Taken behind the studio's write lock, so two buyers asking in the same instant are
    serialised: the second reads the first one's row. The same ``holder`` (one run's
    correlation id) may take it again inside its own block (the day's staircase, then each
    stair it buys): the row then names the step being bought and is given back as it was.

    The holder's process renews the row while the block runs (`_LeaseKeeper`, every
    ``LEASE_RENEW_SECONDS``), never further ahead than ``LEASE_STALE_SECONDS`` and never past
    ``ttl_seconds`` from its start. A row past its expiry was left by a process that is gone:
    it is taken over, and what that holder left (its budget hold, the Owner's spent yes) is
    settled and told to him (`reclaim_abandoned_leases`).
    """
    from app.db import lock_for_write  # noqa: PLC0415

    ttl = int(ttl_seconds or DEFAULT_LEASE_SECONDS)
    holder = str(holder)[:100]
    nested_step: str | None = None
    missing = False
    abandoned: dict[str, Any] | None = None
    ceiling: datetime | None = None
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        now = _now()
        row = session.get(FilmPurchaseLease, storyboard_id)
        live = row is not None and (
            row.expires_at > now.isoformat() or _alive_here(storyboard_id, row.holder)
        )
        if row is not None and live and row.holder != holder:
            view = _lease_view(row)
            raise FilmBusy(_busy_reason(view), view)
        if session.get(Storyboard, storyboard_id) is None:
            # No film: nothing to buy and nothing to hold. The step itself says it is not found.
            missing = True
            view = {"storyboard_id": storyboard_id, "holder": holder, "step": step}
        elif step != CLOSE_LEASE_STEP and film_is_closed(session, storyboard_id):
            # Read behind the write lock the Owner's close also takes (it holds this lease
            # while it closes): a holder either finished before the close or meets it here.
            raise FilmClosed(storyboard_id)
        elif row is not None and live:
            nested_step = row.step
            row.step = step[:20]
            view = _lease_view(row)
        else:
            if row is not None:
                abandoned = {**_lease_view(row), "why": "expired"}
                session.delete(row)
                session.flush()
            ceiling = now + timedelta(seconds=ttl)
            row = FilmPurchaseLease(
                storyboard_id=storyboard_id,
                holder=holder,
                step=step[:20],
                acquired_at=now.isoformat(),
                expires_at=min(ceiling, now + timedelta(seconds=LEASE_STALE_SECONDS)).isoformat(),
            )
            session.add(row)
            session.flush()
            view = _lease_view(row)
    if abandoned is not None:
        try:
            _settle_abandoned(engine, abandoned, correlation_id=holder)
        except Exception as exc:  # noqa: BLE001 - the new purchase must not fail on its letter
            logger.warning(
                "film_lease_settlement_failed",
                extra={"storyboard_id": storyboard_id, "error": type(exc).__name__},
            )
    keeper = (
        _LeaseKeeper(engine, storyboard_id, holder, ceiling)
        if ceiling is not None and not missing
        else None
    )
    try:
        if keeper is not None:
            keeper.start()
        yield view
    finally:
        if keeper is not None:
            keeper.stop()
        if not missing:
            _give_back_lease(engine, storyboard_id, holder, nested_step)


class _LeaseKeeper:
    """Renews a held film lease in the background while its purchase runs, as the worker's
    `LeaseKeeper` renews a task's: a process that is gone renews nothing, so its lease lapses
    within ``LEASE_STALE_SECONDS``; a purchase that runs, however long, is never taken over.
    A missed renewal (a write lock held elsewhere) is logged and tried again at the next one;
    a row that is no longer this holder's, or the lease's ceiling, ends the renewals."""

    def __init__(self, engine: Engine, storyboard_id: str, holder: str, ceiling: datetime) -> None:
        self._engine = engine
        self._storyboard_id = storyboard_id
        self._holder = holder
        self._ceiling = ceiling
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name=f"film-lease-{storyboard_id[:8]}", daemon=True
        )
        self.renewals = 0

    def start(self) -> None:
        with _LIVE_HOLDERS_LOCK:
            _LIVE_HOLDERS.add((self._storyboard_id, self._holder))
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._forget()
        if self._thread.is_alive():
            self._thread.join(timeout=30)

    def _forget(self) -> None:
        with _LIVE_HOLDERS_LOCK:
            _LIVE_HOLDERS.discard((self._storyboard_id, self._holder))

    def _run(self) -> None:
        while not self._stop.wait(float(LEASE_RENEW_SECONDS)):
            try:
                held = self._renew()
            except Exception as exc:  # noqa: BLE001 - one missed renewal is not a lost lease
                logger.warning(
                    "film_lease_renewal_failed",
                    extra={"storyboard_id": self._storyboard_id, "error": type(exc).__name__},
                )
                continue
            if not held:
                # Past its ceiling, or no longer this holder's: not alive here any more.
                self._forget()
                return
            self.renewals += 1

    def _renew(self) -> bool:
        from app.db import lock_for_write  # noqa: PLC0415

        now = _now()
        until = min(self._ceiling, now + timedelta(seconds=LEASE_STALE_SECONDS))
        if until <= now:
            return False
        with Session(self._engine) as session, session.begin():
            lock_for_write(session)
            row = session.get(FilmPurchaseLease, self._storyboard_id)
            if row is None or row.holder != self._holder:
                return False
            row.expires_at = until.isoformat()
        return True


def reclaim_abandoned_leases(
    engine: Engine,
    *,
    correlation_id: str,
    started_at: datetime | None = None,
    timezone: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Take back every film lease whose holder is gone, and settle what it left behind.

    Gone means: the row lapsed (its holder stopped renewing it), or - only when the caller is
    a process that has just started (``started_at``) - the row was taken before that start
    and stands further ahead than any renewing holder ever writes it (a lease from before
    renewals, three hours long). A lease its holder renews, in this process or another
    studio process on the same database, is never touched.

    For each: the row goes, the film's budget hold taken under it is released, an event
    (``media.film_purchase_lease_reclaimed``) records what the holder had done, and the Owner
    gets one letter: what was bought on his yes according to the balance readings, what is
    collected free, and that nothing is bought again unless he presses again."""
    from app.db import lock_for_write  # noqa: PLC0415

    moment = now or _now()
    window = moment + timedelta(seconds=LEASE_STALE_SECONDS + 60)
    taken: list[dict[str, Any]] = []
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        for row in session.scalars(select(FilmPurchaseLease)).all():
            if _alive_here(row.storyboard_id, row.holder):
                # Its holder runs in this process (renewals late after a sleep, a clock jump
                # or a long write lock): not gone, whatever the row says.
                continue
            lapsed = row.expires_at <= moment.isoformat()
            from_before = (
                started_at is not None
                and row.acquired_at < started_at.isoformat()
                and row.expires_at > window.isoformat()
            )
            if lapsed or from_before:
                taken.append({**_lease_view(row), "why": "expired" if lapsed else "before_start"})
                session.delete(row)
    letters: list[str | None] = []
    for view in taken:
        try:
            letters.append(
                _settle_abandoned(engine, view, correlation_id=correlation_id, timezone=timezone)
            )
        except Exception as exc:  # noqa: BLE001 - the lease is back; the rest is told later
            logger.warning(
                "film_lease_settlement_failed",
                extra={"storyboard_id": view["storyboard_id"], "error": type(exc).__name__},
            )
            letters.append(None)
    if taken:
        logger.warning(
            "film_purchase_leases_reclaimed",
            extra={"films": [view["storyboard_id"] for view in taken]},
        )
    return {"reclaimed": [view["storyboard_id"] for view in taken], "letters": letters}


#: The events whose payload carries a reading of the Runway balance, and its key.
_BALANCE_READINGS: dict[str, str] = {
    "media.paid_step_balance_read": "credits",
    "media.stills_step_finished": "balance_after",
    "media.motion_step_finished": "balance_after",
    "media.scene_redone": "balance_after",
}


def _balance_around(session: Session, moment: str) -> tuple[dict | None, dict | None]:
    """The last balance reading before ``moment`` and the first after it, from the books
    (never the vendor): ``{"credits", "at"}`` each, or None."""
    from app.models import DomainEvent  # noqa: PLC0415

    def reading(event: Any) -> dict | None:
        payload = event.payload if isinstance(event.payload, dict) else {}
        value = payload.get(_BALANCE_READINGS[event.event_type])
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return {"credits": float(value), "at": event.timestamp}

    kinds = list(_BALANCE_READINGS)
    before = None
    for event in session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type.in_(kinds), DomainEvent.timestamp < moment)
        .order_by(DomainEvent.sequence.desc())
        .limit(50)
    ):
        before = reading(event)
        if before is not None:
            break
    after = None
    for event in session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type.in_(kinds), DomainEvent.timestamp > moment)
        .order_by(DomainEvent.sequence)
        .limit(50)
    ):
        after = reading(event)
        if after is not None:
            break
    return before, after


def _settle_abandoned(
    engine: Engine,
    view: dict[str, Any],
    *,
    correlation_id: str,
    timezone: str | None = None,
) -> str | None:
    """What a holder that is gone left behind, settled and told: its film's budget holds let
    go, an event, and the Owner's letter. Returns the letter's id."""
    import re  # noqa: PLC0415

    from app.economy.accountant import purchase_abandoned_letter  # noqa: PLC0415
    from app.economy.models import ProviderCostRecord, SpendReservation  # noqa: PLC0415
    from app.models import ApprovalRequest  # noqa: PLC0415
    from app.services import append_event  # noqa: PLC0415

    storyboard_id = str(view["storyboard_id"])
    since = str(view.get("acquired_at") or "")
    # What the holder did lies between its start and the last moment its lease stood (a
    # renewing holder's row lapses a few minutes after it stopped): nothing later is its.
    until = min(str(view.get("expires_at") or _now().isoformat()), _now().isoformat())
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        title = board.title if board is not None else storyboard_id[:8]
        holds = [
            (row.id, int(row.usd_micros))
            for row in session.scalars(
                select(SpendReservation).where(
                    SpendReservation.correlation_id == storyboard_id,
                    SpendReservation.status == "RESERVED",
                    SpendReservation.purpose.like("sheet:%"),
                    SpendReservation.reserved_at >= since,
                    SpendReservation.reserved_at <= until,
                )
            )
        ]
        approvals = list(
            session.scalars(
                select(ApprovalRequest)
                .where(
                    ApprovalRequest.subject == storyboard_id,
                    ApprovalRequest.action.like("media.%"),
                    ApprovalRequest.consumed_at.is_not(None),
                    ApprovalRequest.consumed_at >= since,
                    ApprovalRequest.consumed_at <= until,
                )
                .order_by(ApprovalRequest.consumed_at)
            )
        )
        consumed = [(row.id, str(row.evidence or "")) for row in approvals]
        takes = list(
            session.scalars(
                select(SceneTake).where(
                    SceneTake.storyboard_id == storyboard_id,
                    SceneTake.created_at >= since,
                    SceneTake.created_at <= until,
                )
            )
        )
        submitted = [take.id for take in takes if take.status == "SUBMITTED"]
        delivered = [take.id for take in takes if take.sha256]
        before, after = _balance_around(session, since)
        recorded = 0.0
        if before is not None and after is not None:
            for cost in session.scalars(
                select(ProviderCostRecord).where(
                    ProviderCostRecord.provider == "runway",
                    ProviderCostRecord.recorded_at > before["at"],
                    ProviderCostRecord.recorded_at < after["at"],
                )
            ):
                credits = (cost.attribution_json or {}).get("credits")
                if isinstance(credits, int | float) and not isinstance(credits, bool):
                    recorded += float(credits)
    for hold_id, _micros in holds:
        release_step_hold(
            engine, hold_id, "cumpărare oprită: procesul studioului nu mai rula", correlation_id
        )
    drop = (before["credits"] - after["credits"]) if before and after else None
    unexplained = max(0.0, drop - recorded) if drop is not None else None
    scene = next(
        (int(m.group(1)) for _id, text in consumed if (m := re.search(r"scenei (\d+)", text))),
        None,
    )
    step = str(view.get("step") or "")
    payload = {
        "severity": "WARNING",
        "holder": view.get("holder"),
        "step": step,
        "acquired_at": view.get("acquired_at"),
        "expires_at": view.get("expires_at"),
        "why": view.get("why"),
        "scene_index": scene,
        "approvals_consumed": [approval_id for approval_id, _text in consumed],
        "reservations_released": [hold_id for hold_id, _micros in holds],
        "submitted_takes": submitted,
        "delivered_takes": delivered,
        "balance_before": before,
        "balance_after": after,
        "recorded_credits": round(recorded, 4),
        "unexplained_credits": round(unexplained, 4) if unexplained is not None else None,
    }
    with Session(engine) as session, session.begin():
        append_event(
            session, LEASE_RECLAIMED_EVENT, "storyboard", storyboard_id, 1, payload, correlation_id
        )
    what = (
        f"Refacerea scenei {scene}"
        if step == "scene_redo" and scene is not None
        else LEASE_WORDS_RO.get(step, "Un pas plătit").capitalize()
    )
    text = _abandoned_text(
        what=what,
        title=title,
        step=step,
        started=_clock(view.get("acquired_at"), timezone),
        consumed=consumed,
        submitted=len(submitted),
        delivered=len(delivered),
        before=before,
        after=after,
        recorded=recorded,
        unexplained=unexplained,
        held_micros=sum(micros for _id, micros in holds),
        timezone=timezone,
    )
    return purchase_abandoned_letter(
        engine,
        kind=ABANDONED_LETTER_KIND,
        storyboard_id=storyboard_id,
        subject=f"{what} s-a oprit înainte să se termine",
        body={**payload, "storyboard_id": storyboard_id},
        body_text=text,
        correlation_id=correlation_id,
    )


def _clock(iso: Any, timezone: str | None) -> str:
    """An instant as the Owner reads his clock («03.10.2026 20:36»), UTC when no zone."""
    from zoneinfo import ZoneInfo  # noqa: PLC0415

    try:
        moment = datetime.fromisoformat(str(iso))
    except ValueError:
        return str(iso)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    try:
        zone = ZoneInfo(timezone) if timezone else UTC
    except Exception:  # noqa: BLE001 - an unknown zone reads as UTC, named
        zone = UTC
    label = "" if timezone and zone is not UTC else " UTC"
    return moment.astimezone(zone).strftime("%d.%m.%Y %H:%M") + label


def _abandoned_text(
    *,
    what: str,
    title: str,
    step: str,
    started: str,
    consumed: list[tuple[str, str]],
    submitted: int,
    delivered: int,
    before: dict | None,
    after: dict | None,
    recorded: float,
    unexplained: float | None,
    held_micros: int,
    timezone: str | None,
) -> str:
    """The Owner's letter about a purchase whose process stopped under it, in Romanian."""
    lines = [
        f"Către Owner. {what} a filmului «{title}» a pornit la {started}, iar procesul "
        "studioului s-a oprit înainte să o termine (studioul a fost repornit sau s-a oprit). "
        "Filmul era ținut ocupat de ea; acum este liber."
    ]
    if consumed:
        lines.append(
            "Aprobarea ta pentru ea a fost folosită și nu mai poate cumpăra nimic: "
            + "; ".join(text for _id, text in consumed if text)[:300]
            + "."
        )
    if submitted:
        lines.append(
            f"Furnizorul a primit {count_ro(submitted, 'cerere plătită', 'cereri plătite')}; "
            "numărul sarcinii este în registru, iar imaginile se ridică fără plată și apar pe "
            "foaia de filmare. Nu se cumpără nimic din nou pentru ele."
        )
    elif delivered:
        lines.append(
            f"Studioul a înregistrat {count_ro(delivered, 'imagine', 'imagini')} din ea; "
            "le găsești pe foaia de filmare."
        )
    else:
        lines.append("Studioul nu are nicio imagine sau niciun cadru înregistrat din ea.")
    if before is not None and after is not None:
        first = _clock(before["at"], timezone)
        second = _clock(after["at"], timezone)
        line = (
            f"Soldul Runway: {count_ro(round(before['credits']), 'credit', 'credite')} la ultima "
            f"citire de dinainte ({first}) și "
            f"{count_ro(round(after['credits']), 'credit', 'credite')} la prima citire de după "
            f"({second})."
        )
        if unexplained:
            line += (
                f" Registrul explică {count_ro(round(recorded), 'credit', 'credite')} din "
                f"diferență; {count_ro(round(unexplained), 'credit', 'credite')} lipsesc fără "
                "nicio cumpărătură înregistrată: cel mai probabil plata acestei cereri, primită "
                "de furnizor."
            )
        lines.append(line)
    elif before is not None:
        lines.append(
            f"Ultima citire a soldului Runway de dinainte: "
            f"{count_ro(round(before['credits']), 'credit', 'credite')} "
            f"({_clock(before['at'], timezone)}); studioul nu are încă o citire de după. "
            "Soldul de acum se vede pe site-ul Runway."
        )
    else:
        lines.append("Studioul nu are citiri ale soldului Runway în jurul ei.")
    if held_micros:
        lines.append(f"Rezervarea de buget a pasului ({_ro_usd(held_micros)}) a fost eliberată.")
    again = (
        "apasă din nou «Refă» pe foaia de filmare"
        if step == "scene_redo"
        else "pornește pasul din nou de pe foaia de filmare"
    )
    lines.append(
        f"Nimic nu se cumpără automat. Dacă o vrei, {again}: vei fi întrebat din nou, cu prețul."
    )
    return "\n".join(lines)


def _give_back_lease(
    engine: Engine, storyboard_id: str, holder: str, nested_step: str | None
) -> None:
    """The lease back: deleted by the holder that took it, or its step restored when the same
    holder had taken it again inside its own block. Never raises: a lease left behind
    expires on its own."""
    from app.db import lock_for_write  # noqa: PLC0415

    try:
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            mine = session.get(FilmPurchaseLease, storyboard_id)
            if mine is not None and mine.holder == holder:
                if nested_step is None:
                    session.delete(mine)
                else:
                    mine.step = nested_step
    except Exception:  # noqa: BLE001 - a lease left behind expires on its own
        logger.warning(
            "film_purchase_lease_not_released",
            extra={"storyboard_id": storyboard_id, "holder": holder},
        )


def lease_seconds(settings: Any) -> int:
    """`settings.film_purchase_lease_seconds`, else three hours."""
    value = getattr(settings, "film_purchase_lease_seconds", None)
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return DEFAULT_LEASE_SECONDS


def film_spend_micros(engine: Engine, storyboard_id: str) -> int:
    """What the books already hold for this film, in USD micros: every cost row attributed to
    it (its stills, shots, redos, interrupted steps), the narration of its render jobs, and
    any hold of its own still standing (a step that died under it). Estimates count: an
    estimate is a commitment, and a ceiling that waited for invoices would say "fine" late."""
    from app.economy.models import (  # noqa: PLC0415 - economy imports media
        ProviderCostRecord,
        SpendReservation,
    )
    from app.media.models import VideoRenderJob  # noqa: PLC0415

    attributed = func.json_extract(ProviderCostRecord.attribution_json, "$.storyboard_id")
    rendered = func.json_extract(ProviderCostRecord.attribution_json, "$.render_job_id")
    with Session(engine) as session:
        jobs = list(
            session.scalars(
                select(VideoRenderJob.id).where(VideoRenderJob.storyboard_id == storyboard_id)
            )
        )
        booked = int(
            session.scalar(
                select(func.coalesce(func.sum(ProviderCostRecord.usd_micros), 0)).where(
                    attributed == storyboard_id
                )
            )
            or 0
        )
        voiced = 0
        if jobs:
            voiced = int(
                session.scalar(
                    select(func.coalesce(func.sum(ProviderCostRecord.usd_micros), 0)).where(
                        rendered.in_(jobs), attributed.is_(None)
                    )
                )
                or 0
            )
        held = int(
            session.scalar(
                select(func.coalesce(func.sum(SpendReservation.usd_micros), 0)).where(
                    SpendReservation.status == "RESERVED",
                    SpendReservation.correlation_id == storyboard_id[:36],
                )
            )
            or 0
        )
    return booked + voiced + held


def _settings_of(settings: Any) -> Any:
    from app.media.assembler import _studio_settings  # noqa: PLC0415

    return settings if settings is not None else _studio_settings()


def film_ceiling_micros(
    settings: Any, table: PriceTable | None = None, *, engine: Engine | None = None
) -> tuple[int, str]:
    """(the most one PRODUCTION film may spend, in USD micros; where the figure comes from).

    An explicit film budget wins. Otherwise the Owner's active daily budget is the film's
    ceiling too; shared daily/monthly reservations still bound each actual purchase. Without
    an active daily budget, retain the motion-plus-stills configuration fallback: the motion
    budget and every scene's still as many times as the Owner's renders cap allows it
    (`renders_cap.renders_per_layer`)."""
    from app.media.renders_cap import renders_per_layer  # noqa: PLC0415 - as still_gate was

    chosen = _settings_of(settings)
    figure = getattr(chosen, "film_budget_usd", None)
    if isinstance(figure, int | float) and not isinstance(figure, bool) and figure >= 0:
        return round(float(figure) * 1_000_000), "setare"
    if engine is not None:
        from app.economy.models import SpendingBudget  # noqa: PLC0415

        with Session(engine) as session:
            daily = session.scalar(
                select(func.min(SpendingBudget.limit_usd_micros)).where(
                    SpendingBudget.period == "DAILY", SpendingBudget.active.is_(True)
                )
            )
        if daily is not None:
            return int(daily), "buget_zilnic"
    prices = table or load_price_table()
    motion = getattr(chosen, "motion_budget_usd", None)
    motion_usd = float(motion) if isinstance(motion, int | float) else 12.0
    try:
        per_scene = price_still(STILLS_MODEL, STILLS_RESOLUTION, STILL_CANDIDATES, table=prices)
    except (UnpricedError, KeyError):
        per_scene = 0
    stills = credits_to_micros(
        per_scene * renders_per_layer(settings) * DEFAULT_CEILING_SCENES, prices.credit_usd
    )
    return round(motion_usd * 1_000_000) + stills, "implicit"


def film_budget_view(
    engine: Engine, storyboard_id: str, settings: Any, table: PriceTable | None = None
) -> dict[str, Any]:
    """The film's ceiling as the sheet shows it: the limit, what it already holds, the rest."""
    limit, source = film_ceiling_micros(settings, table, engine=engine)
    spent = film_spend_micros(engine, storyboard_id)
    return {
        "limit_usd_micros": limit,
        "spent_usd_micros": spent,
        "remaining_usd_micros": limit - spent,
        "limit_ro": _ro_usd(limit),
        "spent_ro": _ro_usd(spent),
        "source": source,
    }


def check_film_ceiling(
    engine: Engine,
    storyboard_id: str,
    cap_usd_micros: int,
    *,
    step: str,
    plan_hash: str,
    settings: Any,
    environment: str,
    allow_over_budget: bool,
    correlation_id: str,
    table: PriceTable | None = None,
) -> None:
    """Refuse (`PurchaseGateRefused` OVER_FILM_BUDGET) a PRODUCTION step whose cap would take
    the film past its ceiling; with the Owner's explicit consent, record it and go on.

    TEST films are bounded by their sheet's own cap; the ceiling is the PRODUCTION figure the
    preflight shows the Owner per film, and it is now true (MONEY-07)."""
    from app.services import append_event  # noqa: PLC0415 - services imports media

    if environment != "PRODUCTION":
        return
    view = film_budget_view(engine, storyboard_id, settings, table)
    if view["spent_usd_micros"] + int(cap_usd_micros) <= view["limit_usd_micros"]:
        return
    reason = (
        f"Plafonul filmului de {view['limit_ro']} ar fi depășit: filmul are deja "
        f"{view['spent_ro']} în cărți, iar plafonul pasului este {_ro_usd(cap_usd_micros)}. "
        "Nu se cumpără nimic. Confirmați explicit depășirea pe foaia de filmare, sau ridicați "
        "plafonul unui film (STUDIO_FILM_BUDGET_USD, în configurația studioului)."
    )
    if not allow_over_budget:
        raise PurchaseGateRefused(OVER_FILM_BUDGET, reason)
    with Session(engine) as session, session.begin():
        append_event(
            session,
            FILM_EXCESS_EVENT,
            "storyboard",
            storyboard_id,
            1,
            {
                "step": step,
                "plan_hash": plan_hash,
                "cap_usd_micros": int(cap_usd_micros),
                "film_spent_usd_micros": view["spent_usd_micros"],
                "limit_usd_micros": view["limit_usd_micros"],
                "reason": reason,
                "approved_by": OWNER,
            },
            correlation_id,
        )


def hold_step_budget(
    engine: Engine,
    storyboard_id: str,
    step: str,
    cap_usd_micros: int,
    *,
    plan_hash: str,
    allow_over_budget: bool,
    correlation_id: str,
    detail: dict[str, Any] | None = None,
    step_cap_usd_micros: int | None = None,
) -> str | None:
    """Hold the step's cap, or its next round, against every active budget (`reserve_spend`),
    or refuse.

    The hold is decided behind the write lock, so a second step (another film, the Owner's
    press beside the day) reads it as taken (AR-03: two films were both told the last ten
    dollars were free). Its purpose is ``sheet:<step>`` and its correlation the film. With
    the Owner's explicit consent the sum is held anyway and his consent recorded. Returns the
    reservation id (None when nothing was held: a cap of 0). The caller settles it once the
    purchase is in the books, or lets it go when nothing was bought.

    ``step_cap_usd_micros`` is given when the sum held is only the step's next round (a sheet
    step, `StepHold`): his refusal then names the round and the step's whole cap. A refusal is
    recorded (`STEP_HOLD_REFUSED_EVENT`) for the day's goal to read as the budget spent."""
    from app.economy.budget import reserve_spend  # noqa: PLC0415 - economy imports media
    from app.services import append_event  # noqa: PLC0415

    purpose = f"sheet:{step}"
    hold = reserve_spend(engine, int(cap_usd_micros), purpose, storyboard_id, note=plan_hash[:64])
    if hold["allowed"]:
        return hold.get("reservation_id")
    period = str(hold.get("period") or "DAILY")
    reason = _budget_words(
        engine, period, int(cap_usd_micros), step_cap_usd_micros=step_cap_usd_micros
    )
    if not allow_over_budget:
        _hold_refused(engine, storyboard_id, step, period, int(cap_usd_micros), reason)
        raise PurchaseGateRefused(
            "OVER_DAILY_BUDGET" if period == "DAILY" else "OVER_BUDGET", reason
        )
    forced = reserve_spend(
        engine, int(cap_usd_micros), purpose, storyboard_id, note=plan_hash[:64], force=True
    )
    with Session(engine) as session, session.begin():
        append_event(
            session,
            BUDGET_EXCESS_EVENT,
            "storyboard",
            storyboard_id,
            1,
            {
                "step": step,
                "plan_hash": plan_hash,
                **(detail or {}),
                "period": period,
                "reason": reason,
                "approved_by": OWNER,
            },
            correlation_id,
        )
    return forced.get("reservation_id")


def settle_step_hold(
    engine: Engine, reservation_id: str | None, reference: str, correlation_id: str
) -> None:
    """The step's purchase is in the books: its hold stops counting. Never raises."""
    if not reservation_id:
        return
    from app.economy.budget import settle_reservation  # noqa: PLC0415

    try:
        settle_reservation(
            engine,
            reservation_id,
            settled_reference=reference[:120],
            correlation_id=correlation_id,
        )
    except Exception:  # noqa: BLE001 - the watchdog lets a stale hold go
        logger.warning("step_hold_not_settled", extra={"reservation_id": reservation_id})


def release_step_hold(
    engine: Engine, reservation_id: str | None, reason: str, correlation_id: str
) -> None:
    """Nothing was bought: the step's hold is let go. Never raises."""
    if not reservation_id:
        return
    from app.economy.budget import release_reservation  # noqa: PLC0415

    try:
        release_reservation(engine, reservation_id, reason[:120], correlation_id=correlation_id)
    except Exception:  # noqa: BLE001 - the watchdog lets a stale hold go
        logger.warning("step_hold_not_released", extra={"reservation_id": reservation_id})


def close_step_hold(
    engine: Engine,
    reservation_id: str | None,
    *,
    spent_credits: float | None,
    booked: dict[str, Any] | None,
    reference: str,
    correlation_id: str,
) -> None:
    """After a step: settled when its purchase is in the books, let go when it bought nothing.
    A purchase the books refused keeps its hold (the money still counts against the day) until
    the watchdog's TTL; the refusal is already its own letter."""
    if not spent_credits or float(spent_credits) <= 0:
        release_step_hold(engine, reservation_id, "nimic cumpărat", correlation_id)
    elif booked is not None:
        settle_step_hold(engine, reservation_id, reference, correlation_id)


@dataclass
class StepHold:
    """A paid step's hold on the budgets: its next round, grown before each later one.

    2026-10-16 (the montage): a step held its whole cap at its start, three times every still
    of every row. A 37-row episode's stills held 10,83 USD of the day's 20 while their first
    round cost 3,61, so the day's second film was refused OVER_DAILY_BUDGET before its first
    still. Now the step holds its first round with its GPU starts (the plan's
    ``cost_credits``), and before every later purchase the same row grows to what the step has
    committed plus what it is about to send (`economy.budget.extend_reservation`, behind the
    write lock). It never grows past the step's cap, and only within what every active budget
    has left. A round the budget cannot hold whole is cut to what is held. When nothing fits,
    the step ends on what it bought with the budget's words (``refusal``). The day reads that
    end as OVER_DAILY_BUDGET (``budget_stop``, `runbook.stages._walk_staircase`), the same path
    as a step refused at its start, never as a fault of the film. The film's ceiling is still
    checked against the whole cap before the step starts (`check_film_ceiling`).

    What the step has already committed is held too, at once, whatever its estimate said
    (`hold_spent`): RunPod's measured GPU time raises the meter after a round, and a vendor's
    quote above the price is committed whole. Review of 8f5c6ec: a round held at its 0,25 USD
    estimate measured 0,52, the hold stayed at 0,25 until the books settled it, and a second
    film held 0,75 of a 1 USD day beside it."""

    engine: Engine
    storyboard_id: str
    step: str
    cap_credits: float
    credit_usd: float
    correlation_id: str
    reservation_id: str | None = None
    held_micros: int = 0
    #: The budget's refusal of the latest growth asked for a purchase: its period, words and
    #: the sum it needed beyond the hold (period "" when the row itself was no longer held).
    #: None once a later growth is granted whole, or not needed: a round cut, whose rest went
    #: out in the next round, never reads as stopped by the budget (review of 8f5c6ec). Kept
    #: for good once the step ended on it (``stopped``).
    refusal: dict[str, Any] | None = None
    #: Whether the step ended on the budget's words (the stage said so, `budget_words`).
    stopped: bool = False
    #: The most the hold was asked to grow to for money already committed (`hold_spent`), in
    #: micro-dollars: a budget that could not hold a sum is not asked for it again.
    spent_asked_micros: int = 0

    @property
    def covered_credits(self) -> float:
        """The credits the hold covers now."""
        return self.held_micros / (float(self.credit_usd) * 1_000_000)

    def room(self, committed: float, wanted: float = 0.0, *, partial: bool = False) -> float:
        """The credits the step may still commit: the cap's rest, and no more than the hold
        covers once grown for ``wanted`` more on top of ``committed``. ``partial`` (a round of
        many items, cut to fit) lets the hold grow by what the budgets have left when the
        whole round does not fit; a single purchase grows it whole or not at all. What is
        already committed is held first (`hold_spent`)."""
        self.hold_spent(committed)
        rest = float(self.cap_credits) - float(committed)
        if wanted > 0:
            total = min(float(self.cap_credits), float(committed) + float(wanted))
            self._cover(total, partial=partial)
        return min(rest, self.covered_credits - float(committed))

    def hold_spent(self, committed: float) -> None:
        """Grow the hold to what the step has committed, by what the budgets have left.

        The meter can pass the hold after a purchase: RunPod's measured GPU time raises it
        once a round is over (`gpu_batch.run_rounds`), and a vendor's quote above the price is
        committed whole. Until the books settle the step, the budgets read only the hold, so
        another step would take that money as free. It is already spent, so the cap does not
        bound it, nothing is refused and no refusal is recorded: no purchase was stopped. What
        the budgets cannot hold any more reaches the books when the step is settled."""
        target = credits_to_micros(committed, self.credit_usd)
        if target <= max(self.held_micros, self.spent_asked_micros):
            return
        self.spent_asked_micros = target
        asked = self._grow(float(committed), partial=True)
        if asked is not None and not asked[1]["allowed"]:
            logger.warning(
                "step_hold_below_spend",
                extra={
                    "storyboard_id": self.storyboard_id,
                    "step": self.step,
                    "held_usd_micros": self.held_micros,
                    "committed_usd_micros": target,
                },
            )

    def _cover(self, total_credits: float, *, partial: bool) -> None:
        """Grow the hold to ``total_credits`` for a purchase, and keep the budget's answer:
        its refusal, or none when it was granted whole (or the hold already covered it)."""
        asked = self._grow(total_credits, partial=partial)
        if self.stopped:
            return  # the step ended on its refusal: those words stand
        if asked is None or asked[1]["allowed"]:
            self.refusal = None
            return
        add, hold = asked
        period = str(hold.get("period") or "")
        if not period:
            # The row is no longer held (settled, or swept by the watchdog): nothing more is
            # bought on it, and that is not the budget's refusal.
            self.refusal = {"period": "", "reason": str(hold.get("reason") or "")}
            return
        reason = _budget_words(
            self.engine,
            period,
            add,
            step_cap_usd_micros=credits_to_micros(self.cap_credits, self.credit_usd),
        )
        self.refusal = {"period": period, "reason": reason, "need_usd_micros": add}

    def _grow(self, total_credits: float, *, partial: bool) -> tuple[int, dict[str, Any]] | None:
        """Grow the reservation to ``total_credits``; None when it already covers them, else
        the sum asked (micro-dollars) and the budget's answer."""
        from app.economy.budget import extend_reservation, reserve_spend  # noqa: PLC0415

        add = credits_to_micros(total_credits, self.credit_usd) - self.held_micros
        if add <= 0:
            return None
        if self.reservation_id is None:
            # Nothing held yet (a first round priced at nothing): the hold starts here.
            hold = reserve_spend(
                self.engine, add, f"sheet:{self.step}", self.storyboard_id, note="runda pasului"
            )
            self.reservation_id = hold.get("reservation_id")
            grown = add if hold["allowed"] else 0
        else:
            hold = extend_reservation(
                self.engine,
                self.reservation_id,
                add,
                correlation_id=self.correlation_id,
                partial=partial,
            )
            grown = int(hold.get("added_usd_micros") or 0)
        self.held_micros += grown
        return add, hold

    def budget_words(self, committed: float | None = None, wanted: float = 0.0) -> str | None:
        """The refusal's words when the hold, not the cap, is what stops the step's next
        purchase (``wanted`` credits on top of ``committed``, when the caller knows them);
        None when it is the cap (or nothing was refused). Once said, the step is marked as
        ended on them, and a budget's refusal is recorded for the day's goal
        (`STEP_HOLD_REFUSED_EVENT`): only a refusal that stopped a purchase, never a growth
        asked ahead of a retry that was not needed."""
        if self.refusal is None or self.covered_credits >= float(self.cap_credits) - 1e-9:
            return None
        if committed is not None and float(committed) + wanted > float(self.cap_credits) + 1e-9:
            return None  # the cap he approved stops it, whatever the budget has left
        period = str(self.refusal["period"])
        reason = str(self.refusal["reason"])
        if not self.stopped and period:
            need = int(self.refusal.get("need_usd_micros") or 0)
            _hold_refused(self.engine, self.storyboard_id, self.step, period, need, reason)
        self.stopped = True
        return reason

    def budget_stop(self) -> dict[str, str] | None:
        """What the step's result carries when it ended on a budget: the refusal's status,
        period and words, read by the day as his budget (OVER_DAILY_BUDGET / OVER_BUDGET)."""
        if not self.stopped or self.refusal is None or not self.refusal["period"]:
            return None
        period = str(self.refusal["period"])
        return {
            "status": "OVER_DAILY_BUDGET" if period == "DAILY" else "OVER_BUDGET",
            "period": period,
            "reason": str(self.refusal["reason"]),
        }


#: The command type a paid press of the Owner's is remembered under (`CommandRecord`).
PURCHASE_COMMAND = "SheetPurchase"


def recall_purchase(engine: Engine, command_id: str, payload: dict[str, Any]) -> dict | None:
    """What a press with this ``command_id`` already bought, or None when it has not run.

    The same id with another body raises `app.services.CommandConflict`: a mistake, refused
    rather than guessed about. Only a purchase that ran is remembered (`remember_purchase`):
    a refusal changed nothing, so asking again is safe."""
    from app.services import command_hash, recall_command  # noqa: PLC0415

    with Session(engine) as session:
        return recall_command(session, str(command_id), command_hash(payload))


def remember_purchase(
    engine: Engine, command_id: str, payload: dict[str, Any], result: dict[str, Any]
) -> None:
    """Remember what this press bought, so the same press again buys nothing. Never raises:
    the purchase is already in the books, and its answer is not worth losing it over."""
    from app.services import command_hash, remember_command  # noqa: PLC0415

    stored = json.loads(json.dumps(result, default=str))
    try:
        with Session(engine) as session, session.begin():
            remember_command(
                session, str(command_id), PURCHASE_COMMAND, command_hash(payload), stored
            )
    except Exception:  # noqa: BLE001 - a second writer of the same id already remembered it
        logger.warning("purchase_command_not_remembered", extra={"command_id": str(command_id)})


def _budget_words(
    engine: Engine,
    period: str,
    cap_usd_micros: int,
    *,
    step_cap_usd_micros: int | None = None,
) -> str:
    """The Romanian refusal of a period budget for a step's cap, with what is left; for a
    step holding only its next round (``step_cap_usd_micros`` given), the round and the cap."""
    from app.economy.budget import budget_status  # noqa: PLC0415 - economy imports media
    from app.economy.services import format_micros  # noqa: PLC0415

    detail = next((p for p in budget_status(engine)["budgets"] if p["period"] == period), None)
    word = PERIOD_WORDS.get(period, period.lower())
    if detail is None:
        return f"Bugetul {word} ar fi depășit."
    held = (
        f" (din care {detail['reserved_usd']} USD rezervați pentru pași în lucru)"
        if detail.get("reserved_usd_micros")
        else ""
    )
    asked = (
        f"plafonul pasului este {format_micros(cap_usd_micros)} USD"
        if step_cap_usd_micros is None
        else f"runda următoare a pasului cere {format_micros(cap_usd_micros)} USD (plafonul "
        f"pasului, cu reluările, este {format_micros(step_cap_usd_micros)} USD)"
    )
    return (
        f"Bugetul {word} de {detail['limit_usd']} USD ar fi depășit: {asked} și au rămas "
        f"{detail['remaining_usd']} USD{held}. "
        "Confirmați explicit depășirea pe foaia de filmare, sau așteptați perioada următoare."
    )


def _hold_refused(
    engine: Engine, storyboard_id: str, step: str, period: str, need_micros: int, reason: str
) -> None:
    """`STEP_HOLD_REFUSED_EVENT`: the step's next round did not fit a period budget. Never
    raises: the refusal itself stands whatever happens to its record."""
    from uuid import uuid4  # noqa: PLC0415

    from app.services import append_event  # noqa: PLC0415 - services imports media

    try:
        with Session(engine) as session, session.begin():
            append_event(
                session,
                STEP_HOLD_REFUSED_EVENT,
                "storyboard",
                storyboard_id,
                1,
                {
                    "step": step,
                    "period": period,
                    "need_usd_micros": int(need_micros),
                    "reason": reason,
                },
                str(uuid4()),
            )
    except Exception:  # noqa: BLE001 - a refusal is never lost to its bookkeeping
        logger.warning("step_hold_refusal_not_recorded", extra={"storyboard_id": storyboard_id})


#: The books' reference column holds 120 characters; a correlation id is cut to fit.
_REFERENCE_MAX = 120
#: The event of a purchase the books refused to record (a WARNING, and a letter).
COST_NOT_BOOKED_EVENT = "media.step_cost_not_booked"
#: The event of a paid step that failed after it had paid (a WARNING, and a letter).
INTERRUPTED_EVENT = "media.paid_step_interrupted"


def purchase_reference(prefix: str, correlation_id: str) -> str:
    """``prefix:correlation``, cut to the books' column: one reference per purchase."""
    room = _REFERENCE_MAX - len(prefix) - 1
    return f"{prefix}:{str(correlation_id)[: max(room, 8)]}"[:_REFERENCE_MAX]


def book_purchase(
    engine: Engine,
    *,
    storyboard_id: str,
    step: str,
    reference: str,
    credits: float | None,
    measured: bool,
    credit_usd: float,
    correlation_id: str,
    attribution: dict[str, Any] | None = None,
    billing_provider: str = "runway",
) -> dict[str, Any] | None:
    """One purchase of a film's paid step into the books, under its own reference.

    One ESTIMATED Runway cost, so the next budget check sees it. A booking the books refuse
    (a reference already recorded, a value they cannot take) is never silent: a WARNING
    event on the film and a letter from the Accountant to the Owner, then None.
    """
    from app.economy.accountant import booking_refused_letter  # noqa: PLC0415
    from app.economy.services import (  # noqa: PLC0415 - economy imports media
        EconomyError,
        record_provider_cost,
    )
    from app.services import append_event  # noqa: PLC0415

    if not credits or float(credits) <= 0:
        return None
    usd = float(credits) * float(credit_usd)
    try:
        record_provider_cost(
            engine,
            provider=billing_provider,
            external_reference=reference,
            status="ESTIMATED",
            amount=f"{usd:.6f}",
            attribution={
                "storyboard_id": storyboard_id,
                "step": step,
                "credits": round(float(credits), 4),
                "measured": measured,
                **(attribution or {}),
            },
            correlation_id=correlation_id,
        )
    except (EconomyError, ValueError) as exc:
        reason = str(exc)[:300]
        logger.warning(
            "sheet_step_cost_not_recorded",
            extra={"storyboard_id": storyboard_id, "step": step, "reference": reference},
        )
        with Session(engine) as session, session.begin():
            append_event(
                session,
                COST_NOT_BOOKED_EVENT,
                "storyboard",
                storyboard_id,
                1,
                {
                    "severity": "WARNING",
                    "step": step,
                    "reference": reference,
                    "credits": round(float(credits), 4),
                    "usd": round(usd, 6),
                    "reason": reason,
                },
                correlation_id,
            )
        booking_refused_letter(
            engine,
            reference=reference,
            amount_ro=_ro_usd(round(usd * 1_000_000)),
            reason=reason,
            correlation_id=correlation_id,
        )
        return None
    return {"step": step, "credits": round(float(credits), 4), "usd": round(usd, 6)}


def book_step_cost(
    engine: Engine,
    storyboard_id: str,
    step: str,
    plan_hash: str,
    credit_usd: float,
    result: dict[str, Any],
    correlation_id: str,
) -> dict[str, Any] | None:
    """What a bought step cost, into the books at once, whoever pressed it.

    The measured balance drop when the vendor's balance was read before and after, otherwise
    the credits the step committed (``spent_credits_measured`` / ``spent_credits_quoted``).
    The reference is the film, the step, the sheet and the run that bought it
    (``foaie:{film}:{step}:{plan_hash[:16]}:{correlation}``): one row per purchase. Until
    2026-10-02 it was the sheet alone, so a second purchase under an unchanged sheet (a
    scene that failed again on a later day) was refused as a duplicate and dropped at INFO:
    2,040 credits spent, 680 booked. The step's own budget check is the gate before the
    purchase; nothing is reserved ahead of it, because that check would count the hold and
    the cap twice.
    """
    measured = result.get("spent_credits_measured")
    credits = measured if measured is not None else result.get("spent_credits_quoted")
    return book_purchase(
        engine,
        storyboard_id=storyboard_id,
        step=step,
        reference=purchase_reference(
            f"foaie:{storyboard_id}:{step}:{str(plan_hash)[:16]}", correlation_id
        ),
        credits=float(credits) if credits is not None else None,
        measured=measured is not None,
        credit_usd=credit_usd,
        correlation_id=correlation_id,
        attribution={"plan_hash": plan_hash},
        billing_provider=str(result.get("billing_provider") or "runway"),
    )


def interrupted_spend(meter: Any, account: Any, before: float | None) -> tuple[float, bool]:
    """(credits, measured) a step that raised had spent: the balance drop when the account
    can be read again, else what the step counted as possibly charged."""
    after = _read_balance(account)["credits"] if account is not None else None
    if before is not None and after is not None and before - after > 0:
        return float(before - after), True
    return float(getattr(meter, "committed", 0.0) or 0.0), False


def book_interrupted_step(
    engine: Engine,
    storyboard_id: str,
    step: str,
    *,
    reference: str,
    credits: float,
    measured: bool,
    credit_usd: float,
    error: BaseException,
    correlation_id: str,
    attribution: dict[str, Any] | None = None,
    billing_provider: str = "runway",
) -> dict[str, Any] | None:
    """A paid step that raised after it had paid: booked, a WARNING event and the Owner's
    letter. Returns the booking (None when the books refused it, which is its own letter)."""
    from app.economy.accountant import paid_step_interrupted_letter  # noqa: PLC0415
    from app.services import append_event  # noqa: PLC0415
    from app.wording import error_words  # noqa: PLC0415

    booked = book_purchase(
        engine,
        storyboard_id=storyboard_id,
        step=step,
        reference=reference,
        credits=credits,
        measured=measured,
        credit_usd=credit_usd,
        correlation_id=correlation_id,
        attribution={**(attribution or {}), "interrupted": True},
        billing_provider=billing_provider,
    )
    reason = error_words(error)
    usd_micros = round(float(credits) * float(credit_usd) * 1_000_000)
    with Session(engine) as session, session.begin():
        append_event(
            session,
            INTERRUPTED_EVENT,
            "storyboard",
            storyboard_id,
            1,
            {
                "severity": "WARNING",
                "step": step,
                "credits": round(float(credits), 4),
                "measured": measured,
                "booked": booked is not None,
                "error_class": type(error).__name__,
                "reason": reason[:300],
            },
            correlation_id,
        )
    paid_step_interrupted_letter(
        engine,
        storyboard_id=storyboard_id,
        step_words=STEP_WORDS_RO.get(step, step),
        credits_ro=_ro_credits(round(float(credits))),
        amount_ro=_ro_usd(usd_micros),
        booked=booked is not None,
        reason=reason,
        correlation_id=correlation_id,
    )
    return booked


def withdraw_stale_questions(
    engine: Engine,
    storyboard_id: str,
    action: str,
    plan_hash: str,
    *,
    keep: str | None,
    step_words: str,
    correlation_id: str,
) -> list[str]:
    """Withdraw the Owner's older unanswered questions about this step of this film.

    A newer sheet (a new ``plan_hash``) asked for the same step: a question about the old
    sheet can no longer buy anything, because his yes is spent only for the plan it names.
    Each is closed (EXPIRED, never answered) with the Romanian reason and an event, so his
    inbox holds only the question that can still buy something. Returns their ids.
    """
    # The approval row belongs to the Owner's command kernel (app.services): the sheet words
    # the reason, the kernel closes the rows and writes the event.
    from app import services as kernel  # noqa: PLC0415 - services imports media

    reason = (
        f"Retrasă: o foaie de filmare mai nouă cere acum pasul «{step_words}» (planul "
        f"{str(plan_hash)[:12]}…). Întrebarea aceasta era despre foaia de dinainte și nu mai "
        "poate cumpăra nimic; răspundeți la întrebarea nouă."
    )
    with Session(engine) as session, session.begin():
        return kernel.withdraw_superseded_approvals(
            session,
            action=action,
            subject=storyboard_id,
            new_plan_hash=plan_hash,
            keep=keep,
            reason=reason,
            correlation_id=correlation_id,
        )


def recover_paid_takes(
    engine: Engine,
    storyboard_id: str,
    *,
    correlation_id: str,
    image_adapter: Any = None,
    adapter_for_model: Callable[[str], Any] | None = None,
    registry: Any = None,
    environment: str | None = None,
    storage_root: Path | None = None,
    ffmpeg_path: str | None = None,
) -> dict[str, Any]:
    """What was paid for and not settled, settled before the film's next stair is priced.

    Stills and shots the vendor delivered after their step are collected by their task ids
    (a GET each); collected still candidates, and ones a dying process never judged, are
    judged by the stills gate (`stills_stage.settle_stills`); every paid shot nobody checked
    gets clip QC (`assembler.check_unchecked_shots`: vision tokens only, no retry bought).
    Nothing is bought and no yes is asked: what was bought is only looked at. Without this a
    film whose only open scene was such a take waited for ever (2026-10-02, A7)."""
    from app.services import studio_environment  # noqa: PLC0415 - services imports media

    environment = environment or studio_environment(engine)
    stills: dict[str, Any] = {"collected": [], "scenes": []}
    if image_adapter is not None:
        stills = settle_stills(
            engine,
            storyboard_id,
            correlation_id,
            image_adapter=image_adapter,
            registry=registry,
            environment=environment,
            ffmpeg_path=ffmpeg_path,
            storage_root=storage_root,
        )
    collected: list[dict[str, Any]] = []
    rechecked: list[dict[str, Any]] = []
    if adapter_for_model is not None:
        collected = collect_submitted_takes(
            engine,
            collector_for=lambda take: adapter_for_model(str(take.model_id)),
            correlation_id=correlation_id,
            storyboard_id=storyboard_id,
            kinds=SHOT_TAKE_KINDS,
            storage_root=storage_root,
        )
        rechecked = check_unchecked_shots(
            engine,
            storyboard_id,
            correlation_id,
            adapter_for_model=adapter_for_model,
            environment=environment,
            ffmpeg_path=ffmpeg_path,
            registry=registry,
        )
    return {
        "stills_collected": stills.get("collected") or [],
        "stills_judged": stills.get("scenes") or [],
        "shots_collected": collected,
        "shots_checked": rechecked,
    }


def run_sheet_step(
    engine: Engine,
    storyboard_id: str,
    step: str,
    plan_hash: str,
    *,
    correlation_id: str,
    capabilities: Iterable[ModelCapability] | None = None,
    integration_id: str | None = None,
    table: PriceTable | None = None,
    account: Any = None,
    image_adapter: Any = None,
    adapter_for_model: Callable[[str], Any] | None = None,
    registry: Any = None,
    allow_over_budget: bool = False,
    allowed: Iterable[str] | None = None,
    resolution: str | None = None,
    settings: Any = None,
    environment: str | None = None,
    storage_root: Path | None = None,
    ffmpeg_path: str | None = None,
    today: date | None = None,
    unasked: bool = False,
) -> dict[str, Any]:
    """One paid step of the sheet, bought only under the Owner's yes for THIS sheet.

    Raises `SheetStepRefused` (202 NEEDS_APPROVAL with his question, or 409 with the reason)
    when nothing may be bought; otherwise returns what the stage bought.

    ``unasked`` is a step nobody pressed (the day's staircase, FILM_CONTINUE). Its Owner's mode
    is asked before his balance (2026-10-04: under MANUAL the day raised a «top up» card for a
    step the mode refuses anyway), and the stage reads his policy again before every vendor
    request (`mode_guard`, spec 51). False, the default, is his own press on the sheet: the
    balance first, as before, and his press goes on through BLOCKED_MODE and NEEDS_APPROVAL.

    The whole step runs under the film's purchase lease (holder: ``correlation_id``): a second
    buyer of the same film is refused FILM_BUSY («Filmul este deja în lucru») before anything
    is priced. Before the stage, the film's ceiling (PRODUCTION) against the step's cap, and a
    hold of the step's next round against the budgets (`hold_step_budget`, `StepHold`: grown
    before each later round, or the whole cap with his consent to go over); the hold is
    settled once the purchase is in the books and let go on every refusal. A step that ended
    because its next round could not be held carries ``budget_stopped``.
    """
    if step not in SHEET_STEPS:
        raise SheetStepRefused("UNKNOWN_STEP", f"Pas necunoscut: {step}.")
    try:
        with film_purchase_lease(
            engine,
            storyboard_id,
            holder=correlation_id,
            step=step,
            ttl_seconds=lease_seconds(settings),
        ):
            return _run_sheet_step(
                engine,
                storyboard_id,
                step,
                plan_hash,
                correlation_id=correlation_id,
                capabilities=capabilities,
                integration_id=integration_id,
                table=table,
                account=account,
                image_adapter=image_adapter,
                adapter_for_model=adapter_for_model,
                registry=registry,
                allow_over_budget=allow_over_budget,
                allowed=allowed,
                resolution=resolution,
                settings=settings,
                environment=environment,
                storage_root=storage_root,
                ffmpeg_path=ffmpeg_path,
                today=today,
                unasked=unasked,
            )
    except FilmBusy as exc:
        # FILM_BUSY, or FILM_CLOSED for a film the Owner closed (`FilmClosed`).
        raise SheetStepRefused(exc.status, exc.reason_ro) from exc


def _run_sheet_step(
    engine: Engine,
    storyboard_id: str,
    step: str,
    plan_hash: str,
    *,
    correlation_id: str,
    capabilities: Iterable[ModelCapability] | None,
    integration_id: str | None,
    table: PriceTable | None,
    account: Any,
    image_adapter: Any,
    adapter_for_model: Callable[[str], Any] | None,
    registry: Any,
    allow_over_budget: bool,
    allowed: Iterable[str] | None,
    resolution: str | None,
    settings: Any,
    environment: str | None,
    storage_root: Path | None,
    ffmpeg_path: str | None,
    today: date | None,
    unasked: bool = False,
) -> dict[str, Any]:
    """`run_sheet_step` inside the film's purchase lease."""
    from app.media.factory import reference_image_adapter  # noqa: PLC0415
    from app.services import studio_environment  # noqa: PLC0415

    image_adapter = reference_image_adapter(engine, storyboard_id, image_adapter)
    stills_model = str(getattr(image_adapter, "model", None) or STILLS_MODEL)
    ctx = _context(
        engine,
        capabilities=capabilities,
        integration_id=integration_id,
        table=table,
        allowed=allowed,
        resolution=resolution or getattr(settings, "motion_resolution", None),
        stills_model=stills_model,
        today=today,
    )
    sheet = _sheet(engine, storyboard_id, ctx, read_live=False, settings=settings)

    def current_hash(engine_: Engine, board: str) -> str:
        digest: str = _sheet(engine_, board, ctx, read_live=False)["sheet_hash"]
        return digest

    if not plan_hash or plan_hash != sheet["sheet_hash"]:
        raise SheetStepRefused(
            "STALE_PLAN",
            "Foaia de filmare s-a schimbat de când a fost văzută (sau cererea numește altă "
            "foaie): nu se cumpără nimic. Deschideți foaia de filmare din nou și aprobați "
            "planul de acum.",
        )
    environment = environment or studio_environment(engine)
    if environment == "PRODUCTION" and sheet["shot_plan_gaps"]:
        raise SheetStepRefused(
            "NEEDS_SHOT_PLAN",
            "Scenele "
            + ", ".join(map(str, sheet["shot_plan_gaps"]))
            + " nu au promptul scris de model din planul de cadre; nu se cumpără nimic din "
            "prompturi-șablon.",
        )
    if sheet["lint_blocked"]:
        blocks = list(sheet["blocks"])
        raise SheetStepRefused(
            "LINT_BLOCKED",
            sheet["lint_summary_ro"] + " " + " ".join(f["message_ro"] for f in blocks[1:4]),
            findings=blocks,
        )
    info = sheet["steps"][step]
    if not info["to_buy"]:
        raise SheetStepRefused("NOTHING_TO_BUY", info["waiting_ro"] or "Nimic de cumpărat.")

    if environment == "PRODUCTION":
        # This is the last shared entry to a paid step, including an Owner/API
        # press that bypasses the automatic staircase. Neither an old approval
        # for changed words nor an omitted Director review can buy media.
        from app.media.prompt_audit import (  # noqa: PLC0415 - circular runbook imports
            NEEDS_PROMPT_APPROVAL,
            purchase_approval_gaps,
        )

        unaudited = purchase_approval_gaps(
            engine, storyboard_id, step, [int(scene) for scene in info["to_buy"]]
        )
        if unaudited:
            raise SheetStepRefused(
                NEEDS_PROMPT_APPROVAL,
                "Directoarea Sarah nu a aprobat cuvintele actuale ale scenelor "
                + ", ".join(map(str, unaudited))
                + "; nimic nu se cumpără. Cere verificarea sau rescrierea prompturilor.",
            )

    cap = int(info["cap_credits"])
    margin = margin_of(settings)
    if unasked:
        # Nobody pressed this step: the Owner's mode before his balance. A step the Policy
        # Kernel refuses outright (MANUAL, safe mode, no daily budget in PRODUCTION) reads no
        # balance and raises no low-balance card; a question (NEEDS_APPROVAL) still waits for
        # the balance, so he is never asked to buy what the account cannot pay for.
        from app.media.mode_guard import unasked_refusal  # noqa: PLC0415

        refused = unasked_refusal(
            engine,
            SHEET_STEP_ACTIONS[step],
            subject=storyboard_id,
            context={"plan_hash": plan_hash, "cap_credits": cap},
            cost_usd=float(info["cap_usd"]),
        )
        if refused is not None:
            raise SheetStepRefused(str(refused["status"]), str(refused["reason"]))
    source = account
    if source is None:
        if step == STILLS_STEP:
            source = image_adapter
        elif adapter_for_model is not None:
            first = next(
                (s for s in sheet["scenes"] if s["scene_index"] == info["to_buy"][0]), None
            )
            model = (first or {}).get("motion", {}).get("model_id")
            source = adapter_for_model(str(model)) if model else None
    balance = _read_balance(source)
    local_step = balance.get("applicable") is False and (
        cap == 0 or balance.get("billing_mode") == "gpu"
    )
    if balance["credits"] is None and not local_step:
        raise SheetStepRefused(
            "LOW_BALANCE",
            f"Nu se cumpără nimic: {balance['problem']}; soldul trebuie citit înainte de "
            "orice pas plătit.",
        )
    # The Owner's rule (2026-10-03, «Doar pentru runda următoare»): the step starts when the
    # balance holds its next round x the margin. The cap stays the step's ceiling, and the
    # stage reads the balance again before every purchase after the first.
    round_credits = int(info["cost_credits"])
    needed = needed_credits(round_credits, margin)
    if not local_step:
        record_balance_reading(
            engine,
            balance["credits"],
            storyboard_id=storyboard_id,
            step=step,
            needed=needed,
            correlation_id=correlation_id,
        )
    if not local_step and balance["credits"] < needed:
        reason = start_refusal_ro(
            balance["credits"], round_credits, cap, margin, ROUND_WORDS_RO[step]
        )
        _low_balance_card(
            engine,
            storyboard_id,
            sheet,
            step,
            {
                "scene_index": None,
                "credits": float(balance["credits"]),
                "price_credits": round_credits,
                "needed_credits": needed,
                "missing_credits": missing_credits(balance["credits"], needed),
                "reason_ro": reason,
            },
        )
        raise SheetStepRefused(LOW_BALANCE, reason)
    if not local_step:
        _balance_covered(engine, storyboard_id, float(balance["credits"]))
    cap_micros = credits_to_micros(cap, ctx.table.credit_usd)
    # The budgets hold the step's next round, not its cap (`StepHold`, 2026-10-16): the first
    # round with its GPU starts, grown before every later purchase within what the budgets
    # have left. His explicit consent to go over a budget covers the whole cap, held at once.
    held = cap if allow_over_budget else min(cap, round_credits)
    held_micros = credits_to_micros(held, ctx.table.credit_usd)
    try:
        check_film_ceiling(
            engine,
            storyboard_id,
            cap_micros,
            step=step,
            plan_hash=plan_hash,
            settings=settings,
            environment=environment,
            allow_over_budget=allow_over_budget,
            correlation_id=correlation_id,
            table=ctx.table,
        )
        reservation_id = hold_step_budget(
            engine,
            storyboard_id,
            step,
            held_micros,
            plan_hash=plan_hash,
            allow_over_budget=allow_over_budget,
            correlation_id=correlation_id,
            detail={"cap_credits": cap, "cap_usd": info["cap_usd"], "held_credits": held},
            step_cap_usd_micros=None if held == cap else cap_micros,
        )
    except PurchaseGateRefused as exc:
        raise SheetStepRefused(exc.status, exc.reason_ro) from exc
    budget_hold = StepHold(
        engine=engine,
        storyboard_id=storyboard_id,
        step=step,
        cap_credits=float(cap),
        credit_usd=float(ctx.table.credit_usd),
        correlation_id=correlation_id,
        reservation_id=reservation_id,
        held_micros=held_micros if reservation_id else 0,
    )
    reference = purchase_reference(
        f"foaie:{storyboard_id}:{step}:{str(plan_hash)[:16]}", correlation_id
    )

    # What the stage sends and commits, kept up to date as it buys: read below if it raises.
    meter = SpendMeter()
    try:
        if step == STILLS_STEP:
            if image_adapter is None:
                raise SheetStepRefused(
                    "NO_ADAPTER",
                    "Niciun model de imagine conectat și verificat; imaginile nu se pot cumpăra.",
                )
            result = run_stills_stage(
                engine,
                storyboard_id,
                correlation_id,
                plan_hash=plan_hash,
                image_adapter=image_adapter,
                registry=registry,
                environment=environment,
                plan_hash_of=current_hash,
                ffmpeg_path=ffmpeg_path,
                storage_root=storage_root,
                integration_id=integration_id,
                table=ctx.table,
                meter=meter,
                margin=margin,
                unasked=unasked,
                timezone=getattr(settings, "timezone", None),
                budget_hold=budget_hold,
            )
        else:
            if adapter_for_model is None:
                raise SheetStepRefused(
                    "NO_ADAPTER",
                    "Niciun model video conectat și verificat; mișcarea nu se poate cumpăra.",
                )
            result = run_motion_step(
                engine,
                storyboard_id,
                correlation_id,
                step=step,
                plan_hash=plan_hash,
                adapter_for_model=adapter_for_model,
                capabilities=list(ctx.capabilities),
                account=account,
                allowed=ctx.allowed,
                overrides=sheet_overrides(engine, storyboard_id),
                resolution=ctx.resolution,
                settings=settings,
                environment=environment,
                plan_hash_of=current_hash,
                integration_id=integration_id,
                table=ctx.table,
                ffmpeg_path=ffmpeg_path,
                storage_root=storage_root,
                # The vision model the clip check looks through: without it every shot bought
                # here would wait, unchecked, for the Owner's look.
                registry=registry,
                meter=meter,
                unasked=unasked,
                timezone=getattr(settings, "timezone", None),
                budget_hold=budget_hold,
            )
    except SheetStepRefused:
        release_step_hold(
            engine, budget_hold.reservation_id, f"pasul {step} refuzat", correlation_id
        )
        raise
    except (StillsStageRefused, MotionStepRefused) as exc:
        # A stage refuses before it sends anything: nothing to book, nothing held.
        release_step_hold(
            engine, budget_hold.reservation_id, f"pasul {step}: {exc.status}", correlation_id
        )
        raise _step_refused(
            engine, storyboard_id, step, plan_hash, exc, info, cap, correlation_id
        ) from exc
    except Exception as exc:
        # The stage raised after it may have paid. Retried, it would buy the same shots
        # again (REL-01: four purchases on one "database is locked", none booked): what it
        # committed goes into the books now, the Owner gets his letter, and the error is
        # HARD, so neither the runbook's retry nor a second attempt of the day re-runs it.
        if not meter.attempts:
            release_step_hold(
                engine, budget_hold.reservation_id, f"pasul {step} a căzut", correlation_id
            )
            raise  # nothing was sent: the step may be tried again
        credits, measured = interrupted_spend(meter, source, balance["credits"])
        if credits <= 0:
            release_step_hold(
                engine, budget_hold.reservation_id, f"pasul {step} a căzut", correlation_id
            )
            raise  # sent, and refused before anything was made: nothing was charged
        from app.providers.runpod.wiring import billing_name  # noqa: PLC0415

        booked = book_interrupted_step(
            engine,
            storyboard_id,
            step,
            reference=reference,
            credits=credits,
            measured=measured,
            credit_usd=float(ctx.table.credit_usd),
            error=exc,
            correlation_id=correlation_id,
            attribution={"plan_hash": plan_hash, "attempts": meter.attempts},
            billing_provider=billing_name(image_adapter if step == STILLS_STEP else source),
        )
        close_step_hold(
            engine,
            budget_hold.reservation_id,
            spent_credits=credits,
            booked=booked,
            reference=reference,
            correlation_id=correlation_id,
        )
        raise SpentStageError(
            f"Pasul «{STEP_WORDS_RO[step]}» s-a oprit după ce a cumpărat "
            f"({_ro_credits(round(credits))}); nu se reia automat.",
            storyboard_id=storyboard_id,
            step=step,
            credits=credits,
            booked=booked,
        ) from exc
    from app.providers.runpod.wiring import billing_name  # noqa: PLC0415

    result["billing_provider"] = billing_name(image_adapter if step == STILLS_STEP else source)
    # The step ended on the budget (its next round could not be held): the day reads it as
    # his budget, as a step refused at its start, never as a fault of the film.
    result["budget_stopped"] = budget_hold.budget_stop()
    bought = _step_bought(engine, storyboard_id, step, plan_hash, ctx, result, correlation_id)
    spent = bought.get("spent_credits_measured")
    close_step_hold(
        engine,
        budget_hold.reservation_id,
        spent_credits=float(
            spent if spent is not None else bought.get("spent_credits_quoted") or 0
        ),
        booked=bought.get("booked"),
        reference=reference,
        correlation_id=correlation_id,
    )
    short = bought.get("low_balance")
    if isinstance(short, dict):
        # A scene stopped on the balance inside the step: the reading is kept on the books and
        # the Owner gets the card with what the next purchase lacks.
        record_balance_reading(
            engine,
            float(short["credits"]),
            storyboard_id=storyboard_id,
            step=step,
            needed=int(short["needed_credits"]),
            correlation_id=correlation_id,
        )
        _low_balance_card(engine, storyboard_id, sheet, step, short)
    return bought


def _low_balance_card(
    engine: Engine, storyboard_id: str, sheet: dict[str, Any], step: str, short: dict[str, Any]
) -> None:
    """The card in the Owner's Decisions window for a paid step the balance stopped
    (`decisions.sources.film_low_balance`); its letter, if the day writes one, stays."""
    from app.decisions.sources import film_low_balance  # noqa: PLC0415 - decisions read media

    film_low_balance(
        engine,
        storyboard_id,
        title=str(sheet.get("title") or storyboard_id[:8]),
        step_words=STEP_WORDS_RO.get(step, step),
        short=short,
    )


def _balance_covered(engine: Engine, storyboard_id: str, credits: float) -> None:
    """A step of the film started on its balance: its low-balance card is withdrawn when
    that balance covers what the card asks."""
    from app.decisions.sources import film_balance_covered  # noqa: PLC0415

    film_balance_covered(engine, storyboard_id, credits)


def _step_refused(
    engine: Engine,
    storyboard_id: str,
    step: str,
    plan_hash: str,
    exc: StillsStageRefused | MotionStepRefused,
    info: dict[str, Any],
    cap: int,
    correlation_id: str,
) -> SheetStepRefused:
    """The stage's refusal in the sheet's words, with the older questions it withdrew."""
    withdrawn: list[str] = []
    if exc.status == "NEEDS_APPROVAL":
        withdrawn = withdraw_stale_questions(
            engine,
            storyboard_id,
            SHEET_STEP_ACTIONS[step],
            plan_hash,
            keep=exc.approval_id,
            step_words=STEP_WORDS_RO[step],
            correlation_id=correlation_id,
        )
    return SheetStepRefused(
        exc.status,
        exc.reason_ro,
        approval_id=exc.approval_id,
        cost_usd=info["cost_usd"],
        cap_credits=cap,
        findings=exc.findings,
        withdrawn=withdrawn,
    )


def _step_bought(
    engine: Engine,
    storyboard_id: str,
    step: str,
    plan_hash: str,
    ctx: _Context,
    result: dict[str, Any],
    correlation_id: str,
) -> dict[str, Any]:
    """Into the books here, once, whoever pressed the step (the Owner on the sheet or the
    day's staircase), before the next step's budget check reads them."""
    result["booked"] = book_step_cost(
        engine,
        storyboard_id,
        step,
        plan_hash,
        float(ctx.table.credit_usd),
        result,
        correlation_id,
    )
    return result


# ----------------------------------------------------------------- the last step: assemble


def narration_action(usd_micros: int, priced: bool, threshold_usd: float | None) -> str:
    """The narration's action: over the Owner's threshold (T3) when dearer than it or when
    nothing can price it, within it (T2) otherwise."""
    if not priced or threshold_usd is None:
        return NARRATION_ACTION_OVER
    return NARRATION_ACTION_OVER if usd_micros / 1_000_000 > threshold_usd else NARRATION_ACTION


def narration_gate(
    engine: Engine,
    storyboard_id: str,
    plan_hash: str,
    *,
    usd_micros: int,
    priced: bool,
    threshold_usd: float | None,
    requester: str = "video_editor",
    caveat: str = "",
) -> dict[str, Any]:
    """The Policy Kernel's verdict on voicing this film's narration, bound to the sheet.

    Asked through `may_act` with the sheet's ``plan_hash`` and the step as its context, so
    the Owner's answer is spent only for the plan he was shown, as for every paid step; the
    day's assembly and his own click ask the same question about the same plan, and his one
    yes is spent once.
    """
    from app.economy.services import format_micros  # noqa: PLC0415 - economy imports media
    from app.services import may_act  # noqa: PLC0415 - services imports media

    action = narration_action(usd_micros, priced, threshold_usd)
    price = f"{format_micros(usd_micros)} USD" if priced else "preț necunoscut"
    with Session(engine) as session, session.begin():
        verdict: dict[str, Any] = may_act(
            session,
            action,
            requester=requester,
            subject=storyboard_id,
            evidence=(
                f"storyboard {storyboard_id}: narațiunea filmului asamblat din preluările "
                f"aprobate, {price}" + (f" ({caveat})" if caveat else "")
            ),
            cost_usd=usd_micros / 1_000_000 if priced else None,
            context={"plan_hash": plan_hash, "step": ASSEMBLE_STEP},
        )
    return verdict


def _letter_sheet(sheet: dict[str, Any]) -> dict[str, Any]:
    """The sheet in the shape the QC letter prices its redo proposals from."""
    rows = []
    for scene in sheet.get("scenes") or []:
        motion = scene.get("motion") or {}
        rows.append(
            {
                "scene_index": scene.get("scene_index"),
                "kind": scene.get("kind"),
                "still_credits": scene.get("still_credits"),
                "still_price_source": scene.get("still_price_source"),
                "credits": motion.get("credits"),
                "price_source": motion.get("price_source"),
                "model_id": motion.get("model_id"),
                "resolution": motion.get("resolution"),
            }
        )
    return {"credit_usd": sheet.get("credit_usd"), "scenes": rows}


def _qc_letter(qc: dict[str, Any], spend: Any, sheet: dict[str, Any]) -> str:
    """The Owner's QC letter (`qc_report.qc_summary_ro`): what failed, what the film cost in
    measured credits, what is fixed for free and what each paid fix would cost."""
    from app.media.qc_report import qc_summary_ro  # noqa: PLC0415

    kinds = {int(s["scene_index"]): str(s["kind"]) for s in sheet.get("scenes") or []}
    try:
        return qc_summary_ro(
            qc,
            spend if isinstance(spend, dict) else None,
            sheet=_letter_sheet(sheet),
            scene_kinds=kinds,
        )
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        reasons = qc.get("failure_reasons_json") or []
        return (
            f"Controlul calității: {qc.get('status')}. Raportul detaliat nu a putut fi scris "
            f"({type(exc).__name__}: {str(exc)[:160]}). Motivele, așa cum le-a scris "
            "controlul:" + "".join("\n- " + str(reason)[:300] for reason in list(reasons)[:8])
        )


def _leased(step: str) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
    """Run a paid step of a film under its purchase lease (holder: the call's correlation id);
    a second buyer is refused FILM_BUSY («Filmul este deja în lucru») before anything else."""

    def wrap(function: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        @functools.wraps(function)
        def leased(engine: Engine, storyboard_id: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                with film_purchase_lease(
                    engine,
                    storyboard_id,
                    holder=str(kwargs["correlation_id"]),
                    step=step,
                    ttl_seconds=lease_seconds(kwargs.get("settings")),
                ):
                    return function(engine, storyboard_id, *args, **kwargs)
            except FilmBusy as exc:
                # FILM_BUSY, or FILM_CLOSED for a closed film (`FilmClosed`).
                raise SheetStepRefused(exc.status, exc.reason_ro) from exc

        return leased

    return wrap


@_leased(ASSEMBLE_STEP)
def run_assemble_step(
    engine: Engine,
    storyboard_id: str,
    plan_hash: str,
    *,
    correlation_id: str,
    capabilities: Iterable[ModelCapability] | None = None,
    integration_id: str | None = None,
    table: PriceTable | None = None,
    allowed: Iterable[str] | None = None,
    resolution: str | None = None,
    stills_model: str | None = None,
    settings: Any = None,
    environment: str | None = None,
    storage_root: Path | None = None,
    ffmpeg_path: str | None = None,
    registry: Any = None,
    tts_adapter: Any = None,
    tts_adapter_for_scene: Callable[..., Any] | None = None,
    voice_segments_for_scene: Callable[..., Any] | None = None,
    reference_for_scene: Callable[..., Any] | None = None,
    production_plan: dict[str, Any] | None = None,
    allow_over_budget: bool = False,
    requester: str = "video_editor",
    redo_wiring: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The sheet's last step: the film assembled from its takes, its master and its QC.

    Under the Owner's plan (``plan_hash``, the sheet he was shown): every filmed scene must
    have its approved still and an accepted shot, or (in PRODUCTION) his own LOCAL_MOVE,
    otherwise 409 TAKES_NOT_ACCEPTED names each scene and why, before anything is spoken or
    encoded. The narration is the step's only purchase: its price is a line of the sheet and
    part of its hash, checked against the budget and asked through `narration_gate` (202
    with his question, bound to the plan). Then `assemble_from_takes` (which runs
    `qc.require_chosen_fallbacks` again and books the measured spend of the film's steps),
    the narration's cost into the books, quality control and the Owner's QC letter.

    A refusal for its clips (TAKES_NOT_ACCEPTED) is recorded with each scene's seconds
    (`assembler.record_assembly_refused`). A clip too short to be slowed into the span its
    words need (CLIP_SHORT) has its paid motion redo raised by the studio at the right length
    when ``redo_wiring`` (`runbook.stages.sheet_wiring`) is given (`propose_clip_redos`:
    `redo_scene` unasked, so his paid-media rule asks him); each outcome rides on its scene in
    the refusal (``redo``). Nothing is bought without his yes.

    Raises `SheetStepRefused`; returns the film, its QC and the letter.
    """
    from app.economy.accountant import record_render_costs  # noqa: PLC0415
    from app.economy.services import EconomyError  # noqa: PLC0415
    from app.media.assembler import (  # noqa: PLC0415
        ClipsNotAccepted,
        RenderEngineUnavailable,
        RenderStopped,
        TakesMissing,
        assemble_from_takes,
        record_assembly_refused,
    )
    from app.media.qc import evaluate_media_qc  # noqa: PLC0415
    from app.media.services import ReferenceRequired  # noqa: PLC0415
    from app.providers.media_http import MediaProviderError  # noqa: PLC0415
    from app.services import append_event, studio_environment, utc_now  # noqa: PLC0415

    environment = environment or studio_environment(engine)
    ctx = _context(
        engine,
        capabilities=capabilities,
        integration_id=integration_id,
        table=table,
        allowed=allowed,
        resolution=resolution or getattr(settings, "motion_resolution", None),
        stills_model=stills_model,
        today=None,
    )
    sheet = _sheet(engine, storyboard_id, ctx, read_live=False, environment=environment)
    if not plan_hash or plan_hash != sheet["sheet_hash"]:
        raise SheetStepRefused(
            "STALE_PLAN",
            "Foaia de filmare s-a schimbat de când a fost văzută (sau cererea numește altă "
            "foaie): nu se asamblează nimic. Deschideți foaia de filmare din nou și aprobați "
            "planul de acum.",
        )
    info = sheet["steps"][ASSEMBLE_STEP]
    if info["blocked"]:
        message = "Filmul nu se asamblează: " + blocked_words(info["blocked"])
        record_assembly_refused(
            engine,
            storyboard_id,
            correlation_id,
            ClipsNotAccepted(
                [int(item["scene_index"]) for item in info["blocked"]],
                message,
                details=list(info["blocked"]),
            ),
            stage="sheet",
            environment=environment,
        )
        raise SheetStepRefused(
            "TAKES_NOT_ACCEPTED",
            message,
            scenes=_with_redos(
                engine,
                storyboard_id,
                correlation_id,
                info["blocked"],
                redo_wiring=redo_wiring,
                settings=settings,
                registry=registry,
                environment=environment,
            ),
        )

    narration = info["narration"]
    micros = int(narration["usd_micros"])
    voices: list[Any] = [tts_adapter]
    for scene in sheet["scenes"]:
        index = {"scene_index": scene["scene_index"]}
        if tts_adapter_for_scene is not None:
            voices.append(tts_adapter_for_scene(index))
        if voice_segments_for_scene is not None:
            voices.extend(
                part.get("adapter") for part in voice_segments_for_scene(index) or [] if part
            )
    from app.media.factory import paid_vendors_of  # noqa: PLC0415 - factory imports media

    paid_voice = bool(paid_vendors_of(voices))
    characters = int(narration["characters"])
    if tts_adapter is not None or tts_adapter_for_scene is not None:
        # The sheet counts a scene already voiced whatever the voice (it has no adapter);
        # these voices may have to say it again. What they would really buy is asked for,
        # never less: a narration is never bought on a figure smaller than its own.
        exact = narration_to_buy(
            engine,
            storyboard_id,
            tts_adapter=tts_adapter,
            tts_adapter_for_scene=tts_adapter_for_scene,
            voice_segments_for_scene=voice_segments_for_scene,
        )
        if exact > characters:
            characters = exact
            per_1k = narration.get("per_1k_usd_micros")
            micros = (exact * int(per_1k) + 500) // 1000 if per_1k else 0
    # The narration is asked when it has a price, and when a real voice would speak words
    # nobody could price: never bought on an unknown figure without the question.
    asks = characters > 0 and (micros > 0 or (paid_voice and not narration["priced"]))
    gate: dict[str, Any] | None = None
    if asks:
        if micros > 0 and not allow_over_budget:
            over = may_spend_step(engine, micros)
            if over is not None:
                period, reason = over
                # The film's last paid step does not fit what the day has left: the day's
                # goal reads it as the budget spent, like any step's round (2026-10-16).
                _hold_refused(engine, storyboard_id, ASSEMBLE_STEP, period, micros, reason)
                raise SheetStepRefused(
                    "OVER_DAILY_BUDGET" if period == "DAILY" else "OVER_BUDGET", reason
                )
        threshold = getattr(settings, "paid_generation_approval_threshold_usd", None)
        gate = narration_gate(
            engine,
            storyboard_id,
            plan_hash,
            usd_micros=micros,
            priced=bool(narration["priced"]),
            threshold_usd=float(threshold) if threshold is not None else None,
            requester=requester,
        )
        if not gate["allowed"]:
            withdrawn: list[str] = []
            if gate["status"] == "NEEDS_APPROVAL" and gate.get("approval_id"):
                withdrawn = withdraw_stale_questions(
                    engine,
                    storyboard_id,
                    str(gate["action"]),
                    plan_hash,
                    keep=str(gate["approval_id"]),
                    step_words=STEP_WORDS_RO[ASSEMBLE_STEP],
                    correlation_id=correlation_id,
                )
            raise SheetStepRefused(
                str(gate["status"]),
                str(gate["reason"]),
                approval_id=gate.get("approval_id"),
                cost_usd=narration["usd"] if narration["priced"] else None,
                cap_credits=0,
                withdrawn=withdrawn,
            )

    started = utc_now()
    try:
        film = assemble_from_takes(
            engine,
            storyboard_id,
            correlation_id,
            storage_root=storage_root,
            ffmpeg_path=ffmpeg_path,
            reference_for_scene=reference_for_scene,
            tts_adapter=tts_adapter,
            tts_adapter_for_scene=tts_adapter_for_scene,
            voice_segments_for_scene=voice_segments_for_scene,
            environment=environment,
            production_plan=production_plan,
            settings=settings,
            # The registry reaches the mix: the Voice Artist plans the sound through it.
            registry=registry,
        )
    except ClipsNotAccepted as exc:
        # Recorded where it was refused (the pre-check or the render, `assemble_from_takes`).
        # A render refused once the narration was measured had voiced it (babcf272, 18:22
        # UTC): what it bought goes into the books like any failed assembly's; a pre-check
        # refusal left no render job and books nothing.
        _book_failed_assembly(engine, storyboard_id, started, correlation_id)
        readings = {int(item.get("scene_index") or 0): item for item in exc.details}
        raise SheetStepRefused(
            "TAKES_NOT_ACCEPTED",
            exc.message_ro,
            scenes=_with_redos(
                engine,
                storyboard_id,
                correlation_id,
                [
                    {
                        **{
                            key: readings.get(n, {}).get(key)
                            for key in ("code", "clip_seconds", "span", "needed_seconds")
                        },
                        "scene_index": n,
                        "reason_ro": exc.message_ro,
                    }
                    for n in exc.scenes
                ],
                redo_wiring=redo_wiring,
                settings=settings,
                registry=registry,
                environment=environment,
            ),
        ) from exc
    except TakesMissing as exc:
        raise SheetStepRefused("TAKES_MISSING", str(exc)) from exc
    except RenderStopped as exc:
        _book_failed_assembly(engine, storyboard_id, started, correlation_id)
        raise SheetStepRefused("STOPPED", f"Asamblarea s-a oprit: {exc}") from exc
    except RenderEngineUnavailable as exc:
        _book_failed_assembly(engine, storyboard_id, started, correlation_id)
        raise SheetStepRefused("NO_ENGINE", f"Asamblarea nu poate rula: {exc}") from exc
    except (ReferenceRequired, MediaProviderError) as exc:
        _book_failed_assembly(engine, storyboard_id, started, correlation_id)
        raise SheetStepRefused("REFUSED", f"Asamblarea a fost refuzată: {str(exc)[:300]}") from exc

    job_id = str(film["job_id"])
    asset_id = str(film["output_asset_id"])
    try:
        costs: dict[str, Any] = record_render_costs(
            engine,
            job_id,
            correlation_id,
            alert_percent=getattr(settings, "price_change_alert_percent", None),
        )
    except (EconomyError, KeyError, ValueError) as exc:
        costs = {"error": str(exc)[:200]}
    qc = evaluate_media_qc(
        engine,
        asset_id,
        correlation_id,
        settings=settings,
        registry=registry,
        ffmpeg_path=ffmpeg_path,
    )
    release_after_qc(engine, asset_id, correlation_id)
    spend = (film.get("production") or {}).get("credits_measured")
    letter = _qc_letter(qc, spend, sheet)
    with Session(engine) as session, session.begin():
        append_event(
            session,
            ASSEMBLED_EVENT,
            "storyboard",
            storyboard_id,
            1,
            {
                "plan_hash": plan_hash,
                "job_id": job_id,
                "asset_id": asset_id,
                "environment": environment,
                "narration_usd_micros": micros,
                "narration_asked": asks,
                "approval_id": (gate or {}).get("approval_id"),
                "qc_status": qc.get("status"),
            },
            correlation_id,
        )
    return {
        "status": "ASSEMBLED",
        "storyboard_id": storyboard_id,
        "plan_hash": plan_hash,
        "job_id": job_id,
        "asset_id": asset_id,
        "file_path": film.get("file_path"),
        "narration": {**narration, "asked": asks},
        "credits_measured": spend,
        "fallback_gate": (film.get("production") or {}).get("fallback_gate"),
        "costs": costs,
        "qc": qc,
        "qc_letter_ro": letter,
    }


def _with_redos(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    scenes: Sequence[dict[str, Any]],
    *,
    redo_wiring: dict[str, Any] | None,
    settings: Any,
    registry: Any,
    environment: str,
) -> list[dict[str, Any]]:
    """The refused scenes, each clip too short for its words (CLIP_SHORT) with the paid motion
    redo the studio raised for it (``redo``: NEEDS_APPROVAL with his question, or the reason
    it was not raised), when the caller passed the sheet's wiring. Without it the scenes go
    back as they came; the sheet's «Refă mișcarea» is priced at the right length either way.

    2026-10-09 (babcf272): four refusals of scene 3 ended as letters and nothing moved the
    film; the refusal now raises the one step that can (his yes still decides)."""
    from app.media.assembler import propose_clip_redos  # noqa: PLC0415

    found = [dict(item) for item in scenes]
    short = sorted({int(item["scene_index"]) for item in found if item.get("code") == CLIP_SHORT})
    if not short or redo_wiring is None:
        return found
    try:
        outcomes = propose_clip_redos(
            engine,
            storyboard_id,
            correlation_id,
            wiring=redo_wiring,
            settings=settings,
            registry=registry,
            environment=environment,
            scenes=short,
        )
    except (SceneRedoRefused, UnpricedError, ValueError) as exc:
        logger.warning(
            "clip_redo_not_raised",
            extra={"storyboard_id": storyboard_id, "reason": str(exc)[:200]},
        )
        return found
    by_scene = {int(outcome["scene_index"]): outcome for outcome in outcomes}
    for item in found:
        outcome = by_scene.get(int(item["scene_index"]))
        if outcome is not None:
            item["redo"] = {
                key: outcome.get(key)
                for key in (
                    "status",
                    "approval_id",
                    "billed_seconds",
                    "cost_usd",
                    "cap_usd",
                    "reason_ro",
                )
            }
    return found


def _book_failed_assembly(
    engine: Engine, storyboard_id: str, since: str, correlation_id: str
) -> int:
    """What an assembly that failed after it started had bought (its narration), into the
    books, as the day's own path does (`runbook.stages._record_failed_attempt`): the render
    job this attempt left FAILED, read for what it voiced. Returns the rows written.

    Until 2026-10-02 the sheet's own assemble step raised on these failures and booked
    nothing it had voiced (MONEY-12). A narration kept as a take is not bought again by the
    next attempt, so the next attempt's books do not count it twice.
    """
    from app.economy.accountant import AccountantError, record_failed_render_cost  # noqa: PLC0415
    from app.economy.services import EconomyError  # noqa: PLC0415
    from app.media.models import VideoRenderJob  # noqa: PLC0415

    with Session(engine) as session:
        job_id = session.scalar(
            select(VideoRenderJob.id)
            .where(
                VideoRenderJob.storyboard_id == storyboard_id,
                VideoRenderJob.status == "FAILED",
                VideoRenderJob.started_at >= since,
            )
            .order_by(VideoRenderJob.started_at.desc())
        )
    if job_id is None:
        return 0
    try:
        charged = record_failed_render_cost(engine, str(job_id), correlation_id=correlation_id)
    except (AccountantError, EconomyError, ValueError):
        logger.warning("failed_assembly_cost_not_recorded", extra={"storyboard_id": storyboard_id})
        return 0
    return int(charged["recorded"])


# --------------------------------------------------------------- the studio's own wiring
#
# What the routes use when no test injected its fakes: the Runway connection the Owner
# selected and verified, its catalogue's capabilities, its balance and its adapters. Building
# any of these opens no connection; only `credit_balance()` and a purchase do.

#: Statuses that mean the vendor itself answered (factory.VERIFIED_STATUSES).
_VERIFIED = ("VERIFIED", "ACCESS_VERIFIED")


def runway_connection_id(engine: Engine) -> str | None:
    """The Runway connection the Owner selected for video (or images), else the only verified
    one; None when there is none."""
    from app.integrations.models import Integration, ServiceSelection  # noqa: PLC0415

    with Session(engine) as session:
        for purpose in ("video", "image"):
            selection = session.get(ServiceSelection, purpose)
            if selection is None or not selection.integration_id:
                continue
            row = session.get(Integration, selection.integration_id)
            if row is not None and row.kind in ("runway", "comfyui", "runpod"):
                return str(row.id) if row.status in _VERIFIED else None
            if purpose == "video":
                return None
        rows = session.scalars(
            select(Integration)
            .where(Integration.kind == "runway", Integration.status.in_(_VERIFIED))
            .order_by(Integration.id)
        ).all()
        return str(rows[0].id) if len(rows) == 1 else None


def connection_capabilities(engine: Engine, integration_id: str | None) -> list[ModelCapability]:
    """The motion models of the connection, as the per-scene choice reads them."""
    if not integration_id:
        return []
    from app.media.production_policy import scene_model_capabilities  # noqa: PLC0415

    with Session(engine) as session:
        return scene_model_capabilities(session, integration_id)


def motion_clip_limit(engine: Engine) -> tuple[str, int] | None:
    """The motion model the studio films with and its longest single clip: the cloud profile
    the Owner selected, else the local one (the order the per-scene choice takes them in),
    else the longest clip among the models he allows. None when no connection is selected or
    no model states a maximum: there is nothing to measure a scene against. Reads only."""
    integration_id = runway_connection_id(engine)
    capabilities = connection_capabilities(engine, integration_id)
    if not capabilities:
        return None
    table = price_table_for(engine, integration_id)
    selected = [c for c in capabilities if c.selected_default and not c.local_generation] or [
        c for c in capabilities if c.selected_default and c.local_generation
    ]
    candidates = selected[:1] or [c for c in capabilities if c.owner_allowed and c.admitted]
    limits: list[tuple[int, str]] = []
    for capability in candidates:
        longest = longest_seconds(capability.model_id, table=table, contract=capability.seconds)
        if longest is not None:
            limits.append((longest, capability.model_id))
    if not limits:
        return None
    most, model_id = max(limits)
    return model_id, most


def connection_account(engine: Engine, vault: Any, integration_id: str | None) -> Any:
    """Something whose ``credit_balance()`` reads this connection's balance, or None."""
    if not integration_id:
        return None
    from app.integrations.models import Integration  # noqa: PLC0415
    from app.providers.media_http import MediaProviderNotConfigured  # noqa: PLC0415
    from app.providers.runway import RunwayVideoAdapter  # noqa: PLC0415

    with Session(engine) as session:
        row = session.get(Integration, integration_id)
        if row is None or row.status not in _VERIFIED:
            return None
        if row.kind == "runpod":
            from app.providers.runpod.wiring import connection  # noqa: PLC0415

            return connection(engine, vault, row)
        if row.kind == "comfyui":
            from app.providers.comfyui import ComfyConnection  # noqa: PLC0415

            return ComfyConnection(dict(row.config))
        try:
            key = str((vault.decrypt(row.encrypted_secrets) or {}).get("api_key") or "")
        except Exception:  # noqa: BLE001 - an unreadable secret is simply no account
            return None
    try:
        return RunwayVideoAdapter(key, None, {})
    except MediaProviderNotConfigured:
        return None


def connection_video_adapters(
    engine: Engine, vault: Any, integration_id: str | None
) -> Callable[[str], Any] | None:
    """``adapter_for_model`` for this connection: the model's adapter, carrying its contract."""
    if not integration_id:
        return None
    from app.media.factory import video_provider_for  # noqa: PLC0415

    def adapter_for_model(model_id: str) -> Any:
        return video_provider_for(
            engine,
            vault,
            {"valid": True, "integration_id": integration_id, "model_id": model_id},
        )

    return adapter_for_model


# ------------------------------------------------------------------------ card preview


def card_preview_png(
    engine: Engine, storyboard_id: str, scene_index: int, *, ffmpeg_path: str | None = None
) -> bytes:
    """The last frame of a card scene as the film will show it: composed locally, 0 credits.

    The background is the film's first approved still (blurred and darkened), as in the film;
    a BLACK card is pure black.
    """
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == storyboard_id)
                .order_by(StoryboardScene.scene_index)
            )
        )
        scene = next((row for row in rows if row.scene_index == int(scene_index)), None)
        if scene is None:
            raise SheetNotFound(f"Scena {scene_index} nu există în acest storyboard.")
        kind = scene_kind_of({"scene_kind": scene.scene_kind})
        if kind not in CARD_KINDS:
            raise SheetChoiceRefused(f"Scena {scene_index} este filmată, nu un card compus.")
        card_json = dict(scene.card_json) if isinstance(scene.card_json, dict) else None
        span = max(2.5, float(scene.duration_seconds or 0.0))
        background: str | None = None
        for row in rows:
            if scene_kind_of({"scene_kind": row.scene_kind}) != "LIVE":
                continue
            still = usable_take(
                session,
                storyboard_id,
                int(row.scene_index),
                "still",
                still_options(engine, scene_view(row)),
                statuses=("APPROVED",),
            )
            background = still.path if still is not None else None
            break
    try:
        spec = card_spec_from_json(kind, card_json)
    except CardError as exc:
        raise SheetChoiceRefused(str(exc)) from exc
    binary = ffmpeg_path or find_ffmpeg()
    if not binary:
        raise SheetChoiceRefused("FFmpeg lipsește; previzualizarea cardului nu poate fi compusă.")
    with tempfile.TemporaryDirectory(prefix="amn_card_preview_") as work:
        clip = Path(work) / "card.mp4"
        frame = Path(work) / "card.png"
        compose_card(spec, clip, duration=span, background_still=background, ffmpeg=binary)
        subprocess.run(  # noqa: S603 - a local encoder, arguments built here
            [
                binary,
                "-nostdin",
                "-v",
                "error",
                "-sseof",
                "-0.2",
                "-i",
                str(clip),
                "-frames:v",
                "1",
                "-y",
                str(frame),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        return frame.read_bytes()
