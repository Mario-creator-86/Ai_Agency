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
import hashlib
import json
import logging
import math
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.media.assembler import (
    MOTION_STEP,
    MOTION_STEP_ACTIONS,
    TEST_SHOT_STEP,
    MotionStepRefused,
    SceneRedoRefused,
    _scene_clip_refusal,
    _shot_take,
    clip_accepted,
    clip_qc_of,
    decide_take,
    film_seed,
    motion_fields,
    motion_plan,
    motion_seconds,
    redo_plan,
    release_after_qc,
    run_motion_step,
    scene_kind_of,
    scene_view,
    still_fields,
    usable_take,
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
    plan_film,
    source_label,
)
from app.media.models import SceneTake, Storyboard, StoryboardScene
from app.media.production_policy import (
    COMPOSED_LABELS_RO,
    LOCAL_MOVE,
    ModelCapability,
    load_film_models,
    need_from_scene,
    plan_scene_models,
)
from app.media.prompt_lint import (
    BLOCK,
    LintScene,
    bible_face_rule,
    has_block,
    lint_film,
    summary_ro,
)
from app.media.stills_stage import (
    STILLS_ACTION,
    STILLS_STEP,
    StillsStageRefused,
    run_stills_stage,
    stills_plan,
)
from app.media.toolchain import find_ffmpeg
from app.wording import count as count_ro

logger = logging.getLogger("studio.media.sheet")

__all__ = [
    "ASSEMBLE_STEP",
    "LOCAL_MOVE",
    "SHEET_STEPS",
    "book_step_cost",
    "may_spend_step",
    "narration_gate",
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
#: The account must hold this much more than a step's cap before the step is asked or bought.
BALANCE_MARGIN = 1.15
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
    if not integration_id:
        return load_price_table()
    from app.economy.credits import measured_price_table  # noqa: PLC0415 - economy imports media

    table: PriceTable = measured_price_table(engine, integration_id)
    return table


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
        append_event(
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
    return {"scene_index": int(scene_index), "model_id": model_id or None}


def decide_sheet_take(
    engine: Engine,
    take_id: str,
    decision: str,
    *,
    note: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """The Owner's look at a take on the contact sheet: APPROVED or REJECTED.

    Approving a still makes it THE still of its scene for its prompt: any other approved still
    of that scene and prompt goes back to PAID (kept, never deleted), so one scene never has
    two pictures the motion could start from.
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
    result = decide_take(
        engine, take_id, decision, decided_by=OWNER, note=note, correlation_id=correlation
    )
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
    return {**result, "superseded": superseded}


# ------------------------------------------------------------------------- the sheet


def _read_balance(account: Any) -> dict[str, Any]:
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


def _take_view(
    take: SceneTake, *, current: bool, clip_qc: dict[str, Any] | None = None
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
        "for_current_prompt": current,
        "file_url": _file_url(take.id) if take.path else None,
        # A shot's clip-QC report as it was kept on its take (None for a still, or a shot
        # nobody checked yet): what the Owner's look on the contact sheet is about.
        "clip_qc": clip_qc,
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
        priced = plan_film(scenes, table=ctx.table, today=ctx.today)
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


def _narration(session: Session, scenes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The narration's price: its characters at the dearest active ElevenLabs price per
    thousand (the figure the day's estimate holds, `economy.budget.estimate_film_cost_micros`).

    It is its own line on the sheet and part of the hashed plan: a new price, or new words,
    is a new sheet. With words and no price it is unpriced, never 0: the step then asks.
    """
    from sqlalchemy import func  # noqa: PLC0415

    from app.economy.models import ProviderPrice  # noqa: PLC0415 - economy imports media

    characters = sum(
        len(" ".join(str(scene.get("voiceover_segment") or "").split())) for scene in scenes
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
    if characters == 0:
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
    return {
        "characters": characters,
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


def _scene_readiness(
    session: Session,
    storyboard_id: str,
    scene: dict[str, Any],
    still: SceneTake | None,
    *,
    environment: str,
    local_moves: set[int],
) -> dict[str, Any]:
    """Whether a LIVE scene can go into the film assembled from takes, and why not.

    The same reading `assemble_from_takes` makes before anything is spoken or encoded: an
    approved still for the prompt as it is now, then an accepted shot (the Owner's APPROVED
    or a passing clip QC) or, in PRODUCTION, his own LOCAL_MOVE for the scene.
    """
    index = int(scene["scene_index"])
    if still is None:
        return {
            "scene_index": index,
            "ok": False,
            "how": None,
            "reason_ro": (
                f"Scena {index} nu are o imagine aprobată pentru promptul de acum; "
                "cumpărați sau aprobați imaginea ei pe foaia de filmare."
            ),
        }
    shot = _shot_take(
        session,
        storyboard_id,
        index,
        motion_fields(scene, str(still.sha256 or ""), from_prompt=False),
        0.0,
    )
    why = ""
    if shot is not None:
        accepted, why = clip_accepted(session, shot, environment)
        if accepted:
            return {"scene_index": index, "ok": True, "how": "shot", "reason_ro": ""}
    else:
        refusal, _record = _scene_clip_refusal(session, storyboard_id, index)
        why = refusal or ""
    if index in local_moves:
        return {
            "scene_index": index,
            "ok": True,
            "how": "local_move",
            "reason_ro": f"Scena {index}: imagine fixă animată local, aleasă de Proprietar.",
        }
    if environment != "PRODUCTION":
        return {
            "scene_index": index,
            "ok": True,
            "how": "still",
            "reason_ro": f"Scena {index}: fără cadru acceptat, rămâne imagine fixă (TEST).",
        }
    return {
        "scene_index": index,
        "ok": False,
        "how": None,
        "reason_ro": (
            (f"{why} " if why else "")
            + f"Scena {index} nu are un cadru acceptat, iar Proprietarul nu a ales "
            "„imagine fixă animată local” pentru ea pe foaia de filmare."
        ),
    }


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


def _sheet(
    engine: Engine,
    storyboard_id: str,
    ctx: _Context,
    *,
    account: Any = None,
    read_live: bool = True,
    face_counter: Callable[..., Any] | None = None,
    environment: str | None = None,
) -> dict[str, Any]:
    from app.media.prompt_agent import motion_prompt_for, shot_plan_gaps  # noqa: PLC0415
    from app.media.qc import owner_local_moves  # noqa: PLC0415 - qc reads the sheet's events
    from app.models import OwnerPolicy  # noqa: PLC0415
    from app.services import (  # noqa: PLC0415 - services imports media
        ACTION_RISK_TIERS,
        paid_media_policy,
        studio_environment,
    )

    environment = environment or studio_environment(engine)

    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise SheetNotFound("Storyboard-ul nu există.")
        title = board.title
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
        gaps = shot_plan_gaps(session, storyboard_id)
        takes = _scene_takes(session, storyboard_id)
        stills: dict[int, SceneTake] = {}
        for scene in scenes:
            index = int(scene["scene_index"])
            if scene_kind_of(scene) != "LIVE":
                continue
            found = usable_take(
                session,
                storyboard_id,
                index,
                "still",
                [still_fields(str(scene["visual_prompt"] or ""), None)],
                statuses=("APPROVED",),
            )
            if found is not None:
                stills[index] = found
        rule, threshold = paid_media_policy(session.get(OwnerPolicy, 1))
        # What the assemble step will find: per filmed scene, a shot it may cut in or the
        # Owner's own LOCAL_MOVE; and each shot's clip-QC report, for his look.
        local_moves = owner_local_moves(session, storyboard_id)
        readiness = [
            _scene_readiness(
                session,
                storyboard_id,
                scene,
                stills.get(int(scene["scene_index"])),
                environment=environment,
                local_moves=local_moves,
            )
            for scene in scenes
            if scene_kind_of(scene) == "LIVE"
        ]
        clip_reports = {
            take.id: clip_qc_of(session, take.id)
            for rows_ in takes.values()
            for take in rows_
            if take.kind in ("test_shot", "motion")
        }
        safety = _safety_moves(session, storyboard_id)
        narration = _narration(session, scenes)
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
            "unpriced_ro": f"Imaginile nu au preț: {exc}.",
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
    needs = [
        need_from_scene({**scene, "duration_seconds": motion_seconds(scene)}, len(scenes))
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
            still_text = " ".join(
                str(package.get("still_prompt") or scene.get("visual_prompt") or "").split()
            )
            motion_text, negative = motion_prompt_for(package, model_id, None)
        lint_scenes.append(
            LintScene(
                scene=index,
                kind=kind,
                still_prompt=still_text,
                motion_prompt=motion_text,
                model_id=entry.get("model_id") if kind == "LIVE" else None,
            )
        )
        still = stills.get(index)
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
            )
        }
        motion["seed"] = seed if kind == "LIVE" else None
        motion["usd"] = round(int(entry.get("usd_micros") or 0) / 1_000_000, 6)
        motion["step_status"] = view.get("status")
        motion["take_id"] = view.get("take_id")
        motion["take_kind"] = view.get("take_kind")
        motion["take_status"] = view.get("take_status")
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
            _take_view(take, current=take.prompt_hash == still.prompt_hash if still else False)
            for take in takes.get(index, [])
            if take.kind == "still" and (still is None or take.id != still.id)
        ]
        shots = [
            _take_view(take, current=True, clip_qc=clip_reports.get(take.id))
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
                "shot_seconds": motion_seconds(scene) if kind == "LIVE" else 0.0,
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
            }
        )

    findings = lint_film(lint_scenes, bible=bible)
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
        }

    steps = {
        STILLS_STEP: {
            **step_view(
                STILLS_STEP,
                stills_step,
                "Toate imaginile scenelor filmate sunt deja aprobate; nu se cumpără nimic.",
            ),
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
        MOTION_STEP: step_view(
            MOTION_STEP,
            moving["steps"][MOTION_STEP],
            "Restul mișcării se cumpără după ce imaginile sunt aprobate și Proprietarul a "
            "aprobat cadrul de probă.",
        ),
    }
    blocked = [item for item in readiness if not item["ok"]]
    paid_left = [name for name in SHEET_STEPS if steps[name]["to_buy"]]
    steps[ASSEMBLE_STEP] = {
        "step": ASSEMBLE_STEP,
        "action": NARRATION_ACTION,
        "tier": ACTION_RISK_TIERS.get(NARRATION_ACTION),
        "environment": environment,
        "ready": not blocked,
        "blocked": [
            {"scene_index": item["scene_index"], "reason_ro": item["reason_ro"]} for item in blocked
        ],
        "scenes": readiness,
        "paid_steps_left": paid_left,
        "narration": narration,
        "cost_usd": narration["usd"],
        "cost_credits": 0,
        "cap_credits": 0,
        "waiting_ro": " ".join(item["reason_ro"] for item in blocked),
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
        "balance_needed_credits": {
            name: math.ceil(steps[name]["cap_credits"] * BALANCE_MARGIN) for name in SHEET_STEPS
        },
        "daily_budget": _daily_budget(engine) if read_live else None,
        "narration": narration,
        **_catalogue_view(policy),
        "audio_redo": None,
        "sheet_hash": digest,
    }
    if read_live:
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
        "reference_images_verified": _reference_verified(),
        "scenes": sheet_scenes,
        "lint": [finding.as_dict() for finding in findings],
        "blocks": [finding.as_dict() for finding in blocks],
        "lint_blocked": has_block(findings),
        "lint_summary_ro": summary_ro(findings) if findings else "",
        "steps": steps,
        "prices": prices,
        "footer": footer,
    }


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
    environment: str | None = None,
) -> dict[str, Any]:
    """The shooting sheet of one film. 0 credits; the only live call is ``account``'s free
    balance read (and the local face count of each approved still, with ``face_counter``).

    ``capabilities`` are the motion models the per-scene choice draws from; the price table
    is the published one with ``integration_id``'s MEASURED prices laid over it.
    ``environment`` (default: the studio's) decides what the assemble step accepts.
    ``read_live`` also adds each scene's redo plans (the «Refă» buttons) to the page.
    """
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
        face_counter=face_counter,
        environment=environment,
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
    the credits the step committed: one ESTIMATED provider cost per step, like every render
    cost, so the next step's budget check sees it. The reference is the film, the step and
    the sheet it was bought under, so the same purchase is never booked twice (a second
    booking of one reference is refused by the books). The step's own budget check is the
    gate before the purchase; nothing is reserved ahead of it, because that check would count
    the hold and the cap twice.
    """
    from app.economy.services import (  # noqa: PLC0415 - economy imports media
        EconomyError,
        record_provider_cost,
    )

    measured = result.get("spent_credits_measured")
    credits = measured if measured is not None else result.get("spent_credits_quoted")
    if not credits or float(credits) <= 0:
        return None
    usd = float(credits) * float(credit_usd)
    try:
        record_provider_cost(
            engine,
            provider="runway",
            external_reference=f"foaie:{storyboard_id}:{step}:{str(plan_hash)[:16]}",
            status="ESTIMATED",
            amount=f"{usd:.6f}",
            attribution={
                "storyboard_id": storyboard_id,
                "step": step,
                "plan_hash": plan_hash,
                "credits": round(float(credits), 4),
                "measured": measured is not None,
            },
            correlation_id=correlation_id,
        )
    except (EconomyError, ValueError):
        logger.info("sheet_step_cost_not_recorded", extra={"storyboard_id": storyboard_id})
        return None
    return {"step": step, "credits": round(float(credits), 4), "usd": round(usd, 6)}


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
    from app.models import ApprovalRequest  # noqa: PLC0415
    from app.services import append_event, utc_now  # noqa: PLC0415 - services imports media

    reason = (
        f"Retrasă: o foaie de filmare mai nouă cere acum pasul «{step_words}» (planul "
        f"{str(plan_hash)[:12]}…). Întrebarea aceasta era despre foaia de dinainte și nu mai "
        "poate cumpăra nimic; răspundeți la întrebarea nouă."
    )
    withdrawn: list[str] = []
    with Session(engine) as session, session.begin():
        for request in session.scalars(
            select(ApprovalRequest).where(
                ApprovalRequest.action == action,
                ApprovalRequest.subject == storyboard_id,
                ApprovalRequest.result.in_(("PENDING", "EXPIRED")),
                ApprovalRequest.decided_at.is_(None),
            )
        ):
            if request.id == keep or request.note:
                continue
            asked_for = request.proposed_diff if isinstance(request.proposed_diff, dict) else {}
            if asked_for.get("plan_hash") == plan_hash:
                continue
            previous = request.result
            request.result = "EXPIRED"
            request.note = reason
            append_event(
                session,
                WITHDRAWN_EVENT,
                "owner_approval_request",
                request.id,
                2,
                {
                    "action": action,
                    "subject": storyboard_id,
                    "previous_result": previous,
                    "old_plan_hash": asked_for.get("plan_hash"),
                    "new_plan_hash": plan_hash,
                    "replaced_by": keep,
                    "reason": reason,
                    "withdrawn_at": utc_now(),
                },
                correlation_id,
            )
            withdrawn.append(request.id)
    return withdrawn


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
) -> dict[str, Any]:
    """One paid step of the sheet, bought only under the Owner's yes for THIS sheet.

    Raises `SheetStepRefused` (202 NEEDS_APPROVAL with his question, or 409 with the reason)
    when nothing may be bought; otherwise returns what the stage bought.
    """
    from app.services import append_event, studio_environment  # noqa: PLC0415

    if step not in SHEET_STEPS:
        raise SheetStepRefused("UNKNOWN_STEP", f"Pas necunoscut: {step}.")
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
    sheet = _sheet(engine, storyboard_id, ctx, read_live=False)

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

    cap = int(info["cap_credits"])
    margin = float(getattr(settings, "paid_step_balance_margin", None) or BALANCE_MARGIN)
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
    if balance["credits"] is None:
        raise SheetStepRefused(
            "LOW_BALANCE",
            f"Nu se cumpără nimic: {balance['problem']}; soldul trebuie citit înainte de "
            "orice pas plătit.",
        )
    needed = math.ceil(cap * margin)
    if balance["credits"] < needed:
        raise SheetStepRefused(
            "LOW_BALANCE",
            f"Sold Runway insuficient: {balance['credits']:.0f} credite, iar pasul are plafonul "
            f"de {cap} credite plus marja de {round((margin - 1) * 100)}% ({needed} credite). "
            "Alimentați contul înainte de aprobare.",
        )
    over = may_spend_step(engine, credits_to_micros(cap, ctx.table.credit_usd))
    if over is not None:
        period, reason = over
        if not allow_over_budget:
            raise SheetStepRefused(
                "OVER_DAILY_BUDGET" if period == "DAILY" else "OVER_BUDGET", reason
            )
        with Session(engine) as session, session.begin():
            append_event(
                session,
                "media.budget_excess_approved",
                "storyboard",
                storyboard_id,
                1,
                {
                    "step": step,
                    "plan_hash": plan_hash,
                    "cap_credits": cap,
                    "cap_usd": info["cap_usd"],
                    "period": period,
                    "reason": reason,
                    "approved_by": OWNER,
                },
                correlation_id,
            )

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
            )
    except (StillsStageRefused, MotionStepRefused) as exc:
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
        raise SheetStepRefused(
            exc.status,
            exc.reason_ro,
            approval_id=exc.approval_id,
            cost_usd=info["cost_usd"],
            cap_credits=cap,
            findings=exc.findings,
            withdrawn=withdrawn,
        ) from exc
    # Into the books here, once, whoever pressed the step (the Owner on the sheet or the
    # day's staircase), before the next step's budget check reads them.
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
    )
    from app.media.qc import evaluate_media_qc  # noqa: PLC0415
    from app.media.services import ReferenceRequired  # noqa: PLC0415
    from app.providers.media_http import MediaProviderError  # noqa: PLC0415
    from app.services import append_event, studio_environment  # noqa: PLC0415

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
        raise SheetStepRefused(
            "TAKES_NOT_ACCEPTED",
            "Filmul nu se asamblează: " + " ".join(i["reason_ro"] for i in info["blocked"]),
            scenes=info["blocked"],
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
    # The narration is asked when it has a price, and when a real voice would speak words
    # nobody could price: never bought on an unknown figure without the question.
    asks = narration["characters"] > 0 and (micros > 0 or (paid_voice and not narration["priced"]))
    gate: dict[str, Any] | None = None
    if asks:
        if micros > 0 and not allow_over_budget:
            over = may_spend_step(engine, micros)
            if over is not None:
                period, reason = over
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
        )
    except ClipsNotAccepted as exc:
        raise SheetStepRefused(
            "TAKES_NOT_ACCEPTED",
            exc.message_ro,
            scenes=[{"scene_index": n, "reason_ro": exc.message_ro} for n in exc.scenes],
        ) from exc
    except TakesMissing as exc:
        raise SheetStepRefused("TAKES_MISSING", str(exc)) from exc
    except RenderStopped as exc:
        raise SheetStepRefused("STOPPED", f"Asamblarea s-a oprit: {exc}") from exc
    except RenderEngineUnavailable as exc:
        raise SheetStepRefused("NO_ENGINE", f"Asamblarea nu poate rula: {exc}") from exc
    except (ReferenceRequired, MediaProviderError) as exc:
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
            if row is not None and row.kind == "runway" and row.status in _VERIFIED:
                return str(row.id)
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
                [still_fields(str(row.visual_prompt or ""), None)],
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
