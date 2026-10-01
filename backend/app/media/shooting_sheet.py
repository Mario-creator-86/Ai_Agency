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
    decide_take,
    film_seed,
    motion_plan,
    motion_seconds,
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

logger = logging.getLogger("studio.media.sheet")

__all__ = [
    "LOCAL_MOVE",
    "SHEET_STEPS",
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
#: Each step's action in the Policy Kernel (and so its tier and its Owner's question).
SHEET_STEP_ACTIONS: dict[str, str] = {STILLS_STEP: STILLS_ACTION, **MOTION_STEP_ACTIONS}
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
    ) -> None:
        super().__init__(reason_ro)
        self.status = status
        self.reason_ro = reason_ro
        self.approval_id = approval_id
        self.cost_usd = cost_usd
        self.cap_credits = cap_credits
        self.findings = list(findings)

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
            )
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


def _take_view(take: SceneTake, *, current: bool) -> dict[str, Any]:
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


def _sheet(
    engine: Engine,
    storyboard_id: str,
    ctx: _Context,
    *,
    account: Any = None,
    read_live: bool = True,
    face_counter: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    from app.media.prompt_agent import motion_prompt_for, shot_plan_gaps  # noqa: PLC0415
    from app.models import OwnerPolicy  # noqa: PLC0415
    from app.services import (  # noqa: PLC0415 - services imports media
        ACTION_RISK_TIERS,
        paid_media_policy,
    )

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
            _take_view(take, current=True)
            for take in takes.get(index, [])
            if take.kind in ("test_shot", "motion")
        ]
        sheet_scenes.append(
            {
                "scene_index": index,
                "kind": kind,
                "story_purpose": scene.get("story_purpose"),
                "narration": scene.get("voiceover_segment"),
                "planned_seconds": float(scene.get("duration_seconds") or 0.0),
                "shot_seconds": motion_seconds(scene) if kind == "LIVE" else 0.0,
                "prompt_source": package.get("source"),
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
        },
        "hero_scene": policy.get("hero_scene"),
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
            name: math.ceil(step["cap_credits"] * BALANCE_MARGIN) for name, step in steps.items()
        },
        "daily_budget": _daily_budget(engine) if read_live else None,
        "sheet_hash": digest,
    }
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
) -> dict[str, Any]:
    """The shooting sheet of one film. 0 credits; the only live call is ``account``'s free
    balance read (and the local face count of each approved still, with ``face_counter``).

    ``capabilities`` are the motion models the per-scene choice draws from; the price table
    is the published one with ``integration_id``'s MEASURED prices laid over it.
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
    )


def sheet_hash(engine: Engine, storyboard_id: str, **context: Any) -> str:
    """The sheet's hash alone: no balance read, no face count."""
    context.pop("account", None)
    context.pop("face_counter", None)
    context["read_live"] = False
    digest: str = build_sheet(engine, storyboard_id, **context)["sheet_hash"]
    return digest


# ------------------------------------------------------------------------- the steps


def _budget_refusal(engine: Engine, cap_usd_micros: int) -> tuple[str, str] | None:
    """(period, Romanian reason) when the step's cap would exceed an active budget."""
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
    over = _budget_refusal(engine, credits_to_micros(cap, ctx.table.credit_usd))
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
            return run_stills_stage(
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
        if adapter_for_model is None:
            raise SheetStepRefused(
                "NO_ADAPTER",
                "Niciun model video conectat și verificat; mișcarea nu se poate cumpăra.",
            )
        return run_motion_step(
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
        )
    except (StillsStageRefused, MotionStepRefused) as exc:
        raise SheetStepRefused(
            exc.status,
            exc.reason_ro,
            approval_id=exc.approval_id,
            cost_usd=info["cost_usd"],
            cap_credits=cap,
            findings=exc.findings,
        ) from exc


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
