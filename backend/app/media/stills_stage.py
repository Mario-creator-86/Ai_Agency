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
   prompt was not written by the model (NEEDS_SHOT_PLAN); an open lint BLOCK (LINT_BLOCKED);
   a Runway balance below the cap x 1.15, or one that could not be read (LOW_BALANCE).
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
   balance is read before every request (it buys nothing) and the step halts below the
   request's price. The balance before and after gives the measured credits, written on
   each take and, with the Runway integration named, as MEASURED prices.

Nothing here ever asks a video model: the motion step is a separate approval.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.media.assembler import (
    DEFAULT_STORAGE_ROOT,
    LIVE_KIND,
    classify_vendor_failure,
    failure_code_of,
    failure_detail_of,
    record_take,
    scene_kind_of,
    still_fields,
    take_hash,
    usable_take,
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
from app.media.faces import FaceCounter
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
from app.providers.media_http import MediaProviderError

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
#: The account must hold this much more than the cap before the step is asked or bought.
BALANCE_MARGIN = 1.15
#: The failure code a candidate the studio's own gate rejected carries.
GATE_FAILURE_CODE = "LOCAL.STILL_GATE"
#: Failure kinds tried once more on the same words (production_policy.classify_failure).
RETRY_KINDS = ("TRANSIENT", "BAD_OUTPUT")

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


@dataclass
class _Ledger:
    """What the step has committed, against the approved cap."""

    cap: int
    committed: float = 0.0
    images: int = 0
    take_ids: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------------ the plan


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _read_scenes(engine: Engine, storyboard_id: str) -> tuple[dict[str, Any], list[_Scene]]:
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
            # The take's identity is the scene's planned still (its words and the model), the
            # same identity `assemble_from_takes` looks for. A re-roll's positive words and
            # Figure 1 are how this step reaches that still, not a different still.
            identity = still_fields(visual, None)
            scene = _Scene(
                index=int(row.scene_index),
                kind=kind,
                words=" ".join(words.split()),
                identity=identity,
                look_block=str(package.get("look_block") or ""),
                camera_move=str(package.get("camera_move") or ""),
                source=package.get("source") if isinstance(package.get("source"), str) else None,
            )
            if kind == LIVE_KIND:
                found = usable_take(
                    session, storyboard_id, scene.index, "still", [identity], statuses=("APPROVED",)
                )
                if found is not None:
                    session.expunge(found)
                    scene.reuse = found
            scenes.append(scene)
    return bible, scenes


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
    to_buy = [scene.index for scene in scenes if scene.kind == LIVE_KIND and scene.reuse is None]
    cost = per_scene * len(to_buy)
    cap = cost * (1 + MAX_REROLLS)
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
            }
            for scene in scenes
        ],
        "to_buy": to_buy,
        "credits_per_scene": per_scene,
        "cost_credits": cost,
        "cap_credits": cap,
    }
    plan_hash = hashlib.sha256(_canonical(planned).encode("utf-8")).hexdigest()
    return {
        **planned,
        "credit_usd": prices.credit_usd,
        "cost_usd": round(cost * prices.credit_usd, 6),
        "cap_usd": round(cap * prices.credit_usd, 6),
        "price_source": source_label(row),
        "plan_hash": plan_hash,
    }


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


def _prompt(scene: _Scene, instruction: str, with_figure: bool) -> str:
    parts = [scene.words]
    if instruction:
        parts.append(f"Show {instruction}.")
    if with_figure:
        parts.append(FIGURE_ONE)
    return " ".join(part for part in parts if part)


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


def _buy(
    adapter: Any, prompt: str, references: list[bytes], count: int
) -> tuple[list[Any], float | None]:
    """The candidates of one request and the vendor's price for it (None when unstated)."""
    if callable(getattr(adapter, "generate_candidates", None)):
        results = asyncio.run(
            adapter.generate_candidates(
                prompt, ratio=STILL_RATIO, count=count, references=list(references)
            )
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
        for take_id, report in verdicts:
            row = session.get(SceneTake, take_id)
            if row is None:
                continue
            if chosen is not None and report is chosen:
                row.status = "APPROVED"
                row.approved_by = GATE_REVIEWER
            elif report.decision == "PASSED":
                row.status = "PAID"
            else:
                row.status = "REJECTED"
                row.failure_code = GATE_FAILURE_CODE
                row.failure_detail = ("; ".join(report.reasons_ro) or "respinsă")[:500]


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
) -> dict[str, Any]:
    """The stills step of one film, bought only under the Owner's yes for this plan.

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
    environment = environment or studio_environment(engine)
    bible, scenes = _read_scenes(engine, storyboard_id)
    live = [scene for scene in scenes if scene.kind == LIVE_KIND]

    if environment == "PRODUCTION":
        unwritten = [scene.index for scene in live if scene.source != "model"]
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

    cap = int(plan["cap_credits"])
    read, before, problem = _read_balance(image_adapter) if plan["to_buy"] else (False, None, None)
    if problem is not None:
        raise StillsStageRefused("LOW_BALANCE", f"Nu se cumpără imagini: {problem}.", plan=plan)
    if before is not None and before < cap * BALANCE_MARGIN:
        raise StillsStageRefused(
            "LOW_BALANCE",
            f"Soldul Runway ({before:.0f} credite) este sub plafonul pasului de imagini "
            f"({cap} credite) plus marja de 15%: alimentați contul înainte de aprobare.",
            plan=plan,
        )

    if plan["to_buy"]:
        with Session(engine) as session, session.begin():
            verdict = may_act(
                session,
                STILLS_ACTION,
                requester=requester,
                subject=storyboard_id,
                evidence=f"{len(plan['to_buy'])} scene × {STILL_CANDIDATES} imagini la 2K",
                cost_usd=plan["cost_usd"],
                context={"plan_hash": plan_hash, "cap_credits": cap},
            )
        if not verdict["allowed"]:
            raise StillsStageRefused(
                str(verdict["status"]),
                str(verdict["reason"]),
                approval_id=verdict.get("approval_id"),
                plan=plan,
            )

    faces_forbidden = bible_face_rule(bible) is not None
    rules = _bible_rules(bible)
    per_request = int(plan["credits_per_scene"])
    per_image = per_request / STILL_CANDIDATES
    work_dir = (storage_root or DEFAULT_STORAGE_ROOT) / storyboard_id / "stills"
    work_dir.mkdir(parents=True, exist_ok=True)
    ledger = _Ledger(cap=cap)
    figure_one: bytes | None = None
    first_live = live[0].index if live else None
    results: list[dict[str, Any]] = []
    stopped: str | None = None
    previous_kind: str | None = None
    unverified = False

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
        if stopped is not None:
            entry.update(status="NOT_BOUGHT", reason=stopped)
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
        references = [figure_one] if figure_one is not None and scene.index != first_live else []
        instruction = ""
        rerolls = 0
        retried = False
        outcome: dict[str, Any] | None = None
        while outcome is None:
            if stop_requested(engine):
                stopped = "Proprietarul a oprit autonomia; nu se mai cumpără imagini."
                outcome = {"status": "NOT_BOUGHT", "reason": stopped}
                break
            if ledger.committed + per_request > ledger.cap:
                stopped = (
                    f"STOPPED_AT_CAP: încă o cerere ({per_request} credite) ar depăși plafonul "
                    f"aprobat de {ledger.cap} credite (deja {ledger.committed:.0f})."
                )
                outcome = {"status": "NOT_BOUGHT", "reason": stopped}
                break
            _read, balance, problem = _read_balance(image_adapter)
            if problem is not None or (balance is not None and balance < per_request):
                stopped = (
                    f"Nu se mai cumpără imagini: {problem}."
                    if problem
                    else f"Soldul Runway ({balance:.0f} credite) nu mai acoperă o cerere "
                    f"({per_request} credite)."
                )
                outcome = {"status": "NOT_BOUGHT", "reason": stopped}
                break
            prompt = _prompt(scene, instruction, bool(references))
            try:
                candidates, quoted = _buy(image_adapter, prompt, references, STILL_CANDIDATES)
            except MediaProviderError as exc:
                failure = classify_vendor_failure(exc, previous_kind)
                previous_kind = failure.kind
                ledger.committed += per_request  # a refusal may be paid like a success
                ledger.take_ids.append(
                    record_take(
                        engine,
                        storyboard_id=storyboard_id,
                        scene_number=scene.index,
                        kind="still",
                        prompt_hash=take_hash(scene.identity, model_id),
                        model_id=model_id,
                        resolution=STILL_RATIO,
                        status="REFUSED",
                        correlation_id=correlation_id,
                        failure_code=failure_code_of(exc),
                        failure_detail=failure_detail_of(exc),
                    )
                )
                if failure.kind in RETRY_KINDS and not retried:
                    retried = True
                    continue
                entry.update(failure_kind=failure.kind, failure_code=failure_code_of(exc))
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
            for number, candidate in enumerate(candidates):
                suffix = candidate.format if candidate.format in ("png", "jpeg", "webp") else "png"
                path = work_dir / (
                    f"scene_{scene.index:02d}_{uuid4().hex[:8]}_c{number + 1}."
                    + ("jpg" if suffix == "jpeg" else suffix)
                )
                path.write_bytes(candidate.image_bytes)
                ledger.images += 1
                take_id = record_take(
                    engine,
                    storyboard_id=storyboard_id,
                    scene_number=scene.index,
                    kind="still",
                    prompt_hash=take_hash(scene.identity, model_id),
                    model_id=model_id,
                    resolution=STILL_RATIO,
                    status="PAID",
                    correlation_id=correlation_id,
                    credits_quoted=float(share),
                    path=path,
                    sha256=hashlib.sha256(candidate.image_bytes).hexdigest(),
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
            _event(
                engine,
                "media.still_needs_owner",
                storyboard_id,
                {
                    "severity": "WARNING",
                    "scene_number": scene.index,
                    "status": outcome["status"],
                    "reason": outcome["reason"],
                    "rerolls": rerolls,
                },
                correlation_id,
            )

    after: float | None = None
    measured: float | None = None
    if read:
        _read, after, _problem = _read_balance(image_adapter)
        if before is not None and after is not None and before - after > 0:
            measured = before - after
    if measured is not None and ledger.images:
        each = measured / ledger.images
        with Session(engine) as session, session.begin():
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

    needs_owner = [e["scene_index"] for e in results if e.get("status") == "NEEDS_OWNER"]
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
        "reference_unverified": unverified,
    }
    _event(engine, "media.stills_step_finished", storyboard_id, summary, correlation_id)
    return summary
