"""The Accountant's day: what was spent, against what was allowed, and what to do about it.

The books were kept but nobody read them. `ProviderCostRecord` recorded what a vendor charged,
`treasury_snapshot` said what was spendable, and no employee ever compared the two with a
limit or told the Director. This module is that employee's desk, in two parts that stay
separate on purpose:

- **The numbers are computed, never asked for.** `daily_figures()` reads the day's and the
  month's spend per provider and per status from the books, the active budgets and their
  state, and the usage nobody has priced. A model is not consulted about a sum.
- **The judgement is the Accountant's.** Given those figures as data, the Accountant says
  what stands out, what to hold, and what the Director should decide — as a structured
  answer validated before anything is stored. A budget already exceeded escalates whether or
  not the model agrees; the model's report explains, it does not decide.

Costs are recorded where the studio knows a price (`record_render_costs`): a render's
narration at the stored per-character price of the model that voiced it, or — since the nine
live ElevenLabs models carry no catalogue price — at the Owner's own price for the model
(`provider_price`). A render that failed midway is costed for what was attempted
(`record_failed_render_cost`), because the vendor charges for the shot it made whether or
not the studio brought it home. Usage with no stored price is reported as unpriced, never as
free.

Three letters leave this desk on their own. A day whose film the budget refused was silent —
the stage was SKIPPED and nobody wrote to the Owner; `budget_refusal_letter` writes once a
day. And the Director's loop and the mail rounds spent tokens under no ceiling;
`may_run_agent` is the ceiling, and its refusal is a letter, once a day, not a run per run.
And a SUPERVISED day left one approval request per film in a page nobody was told to open;
`waiting_approvals_letter` names what is standing, what each question would cost, and when the
oldest runs out — once a day, and never when nothing waits.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.agents.identity import blocker_of, clipped
from app.agents.memory import agent_for_role, remember
from app.agents.messages import post_message
from app.agents.models import AgentMessage, AgentRun
from app.db import lock_for_write
from app.economy.budget import _period_start, budget_status, studio_timezone
from app.economy.prices import price_row
from app.economy.services import EconomyError, format_micros, record_provider_cost
from app.factual.sanitizer import wrap_in_inert_boundary
from app.integrations.models import Integration
from app.media.models import VideoRenderJob
from app.media.production_policy import credit_usd, estimate_cost_usd, record_measured_price
from app.providers.registry import ProviderRegistry
from app.services import pending_approvals

ACCOUNTANT_ROLE = "Accountant"
TEMPLATE_VERSION = "accountant-v1"


class AccountantError(ValueError):
    """The report could not be produced or did not match its schema; the figures still stand."""


class NoAccountant(AccountantError):
    """No active employee holds the accounting role."""


# ----------------------------------------------------------------------------- figures


def daily_figures(engine: Engine, now: datetime | None = None) -> dict[str, Any]:
    """Everything the Accountant reads before saying a word. Computed from the books."""
    status = budget_status(engine, now)
    return {
        "today": status["today"],
        "month": status["month"],
        "budgets": [
            {
                "period": b["period"],
                "limit_usd": b["limit_usd"],
                "spent_usd": b["spent_usd"],
                "reserved_usd": b["reserved_usd"],
                "remaining_usd": b["remaining_usd"],
                "ratio": b["ratio"],
                "state": b["state"],
                "warn_ratio": b["warn_ratio"],
            }
            for b in status["budgets"]
        ],
        "measured_at": status["measured_at"],
    }


# ----------------------------------------------------------------------------- render costs


#: The unit of the Owner's price table each purchase falls back to when the catalogue row
#: of the model has no price of its own, and the quantity that unit multiplies.
_PRICE_FALLBACK = {
    "voice": ("per_1k_characters", "characters", 1000.0),
    "image": ("per_generation", "images", 1.0),
    "motion": ("per_second", "seconds", 1.0),
}


def _owner_price_usd(
    session: Session, integration_id: str, model_id: str, unit: str, quantity: dict[str, float]
) -> tuple[float | None, str | None]:
    """The Owner's price for what a scene used, when the catalogue has none. Returns the
    dollars and the price's provenance, or (None, None)."""
    price_unit, key, per = _PRICE_FALLBACK[unit]
    amount = float(quantity.get(key, 0.0))
    if amount <= 0:
        return None, None
    integration = session.get(Integration, integration_id)
    if integration is None:
        return None, None
    row = price_row(session, integration.kind, str(model_id), price_unit)
    if row is None or row.usd_micros <= 0:
        return None, None
    return round(amount * row.usd_micros / 1_000_000 / per, 6), row.provenance


def _priced_scene_costs(
    session: Session,
    render_job_id: str,
    production: dict[str, Any],
    scenes: list[Any],
    *,
    reference_tag: str = "scene",
    voice_integration_id: str | None = None,
) -> tuple[list[dict[str, Any]], int, dict[str, tuple[float, float]], str | None]:
    """Price what each scene bought — narration, still, seconds of film — where a price
    exists: the catalogue's, else the Owner's table. Shared by the finished render and the
    failed one; only the reference differs, so the two can never charge the same scene."""
    priced: list[dict[str, Any]] = []
    unpriced = 0
    # model -> (dollars charged, seconds bought), so a render teaches what a second costs.
    measured: dict[str, tuple[float, float]] = {}
    motion_connection: str | None = None
    raw_image = production.get("image")
    image: dict[str, Any] = raw_image if isinstance(raw_image, dict) else {}
    production_voice = (production.get("voice") or {}).get("integration_id") or voice_integration_id
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        index = scene.get("scene_index")
        voice_integration = scene.get("integration_id") or production_voice
        # Three things can be bought for one scene, each by its own model and unit:
        # the narration, the still, and the seconds of film the still was moved for.
        raw_motion = scene.get("motion")
        motion: dict[str, Any] = raw_motion if isinstance(raw_motion, dict) else {}
        # Which vendor drew *this* scene's still. The film-level record names the first
        # vendor of the chain; a scene the Owner's approved alternative drew was charged to
        # a model that never made it, or priced at nothing when the two vendors differ.
        raw_scene_image = scene.get("image")
        scene_image: dict[str, Any] = (
            raw_scene_image if isinstance(raw_scene_image, dict) else image
        )
        wanted: list[tuple[str, Any, Any, dict[str, float]]] = [
            (
                "voice",
                voice_integration,
                scene.get("model_id"),
                {"characters": float(scene.get("characters") or 0)},
            ),
            (
                "image",
                scene_image.get("integration_id"),
                scene_image.get("model"),
                {"images": 0.0 if scene.get("still") is False else 1.0},
            ),
            (
                "motion",
                motion.get("integration_id"),
                motion.get("model"),
                # The credits Runway named for this shot, and the seconds as the fallback
                # for a vendor that priced the model but said nothing per task.
                {
                    "credits": float(motion.get("estimated_credits") or 0),
                    "seconds": float(motion.get("asked_seconds") or 0),
                },
            ),
        ]
        if motion.get("model") and motion.get("estimated_credits"):
            motion_connection = motion.get("integration_id") or motion_connection
            per_credit = (
                credit_usd(session, motion["integration_id"])
                if motion.get("integration_id")
                else None
            )
            if per_credit:
                usd = float(motion["estimated_credits"]) * per_credit
                seconds = float(motion.get("asked_seconds") or 0)
                before = measured.get(str(motion["model"]), (0.0, 0.0))
                measured[str(motion["model"])] = (before[0] + usd, before[1] + seconds)
        for unit, integration_id, model_id, quantity in wanted:
            if not integration_id or not model_id or not any(quantity.values()):
                continue
            provenance = "catalogue"
            estimate = estimate_cost_usd(
                session,
                integration_id,
                model_id,
                characters=int(quantity.get("characters", 0)),
                images=int(quantity.get("images", 0)),
                seconds=quantity.get("seconds", 0.0),
                credits=quantity.get("credits", 0.0),
            )
            if estimate is None or estimate <= 0:
                # The catalogue row has no price (every live ElevenLabs model): the Owner's
                # own table prices it, and the row says whose price that was.
                estimate, owner_provenance = _owner_price_usd(
                    session, integration_id, model_id, unit, quantity
                )
                provenance = owner_provenance or provenance
            if estimate is None or estimate <= 0:
                unpriced += 1
                continue
            integration = session.get(Integration, integration_id)
            priced.append(
                {
                    "provider": integration.kind if integration else "unknown",
                    "reference": f"render:{render_job_id}:{reference_tag}:{index}:{unit}",
                    "amount": f"{estimate:.6f}",
                    "attribution": {
                        "render_job_id": render_job_id,
                        "scene_index": index,
                        "unit": unit,
                        "model_id": model_id,
                        "price_provenance": provenance,
                        **quantity,
                    },
                }
            )
    return priced, unpriced, measured, motion_connection


def record_render_costs(
    engine: Engine,
    render_job_id: str,
    correlation_id: str | None = None,
    *,
    alert_percent: float | None = None,
) -> dict:
    """Record the estimated cost of one render's narration, per scene, where a price is known.

    The reference is the render job and scene, so re-running the day cannot charge twice.
    Scenes voiced by a model without a stored price are counted and reported, not priced.
    """
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session:
        job = session.get(VideoRenderJob, render_job_id)
        if job is None:
            raise EconomyError("Render job not found")
        production = job.production_json if isinstance(job.production_json, dict) else {}
        scenes = production.get("scenes") or []
        priced, unpriced, measured, motion_connection = _priced_scene_costs(
            session, render_job_id, production, scenes
        )
    # What the vendor charged for this render becomes the model's price. A guess that said
    # 0.025 USD a second survived four renders that measured 0.43; measurement ends that.
    alerts: list[dict[str, Any]] = []
    for model_id, (usd, seconds) in measured.items():
        if seconds > 0 and usd > 0 and motion_connection:
            moves = record_measured_price(
                engine, motion_connection, model_id, usd / seconds, "per second of video"
            )
            for move in moves:
                percent = move.get("percent")
                if (
                    alert_percent is not None
                    and isinstance(percent, int | float)
                    and abs(float(percent)) >= float(alert_percent)
                ):
                    alerts.append({**move, "model_id": model_id})
    if alerts:
        price_change_alert(engine, alerts, correlation)

    recorded = _record_priced(engine, priced, correlation, failed=False)
    return {
        "render_job_id": render_job_id,
        "recorded": recorded,
        "unpriced_scenes": unpriced,
        "price_alerts": alerts,
    }


def _record_priced(
    engine: Engine, priced: list[dict[str, Any]], correlation: str, *, failed: bool
) -> int:
    recorded = 0
    for item in priced:
        try:
            record_provider_cost(
                engine,
                provider=item["provider"],
                external_reference=item["reference"],
                status="ESTIMATED",
                amount=item["amount"],
                attribution={**item["attribution"], "failed": failed},
                correlation_id=correlation,
                failed=failed,
            )
            recorded += 1
        except EconomyError:
            # Already recorded for this scene: the day was re-run, and one scene costs once.
            continue
    return recorded


def record_failed_render_cost(
    engine: Engine,
    job_id: str,
    scenes_attempted: list[dict[str, Any]] | None = None,
    *,
    voice_integration_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """The cost of a render a `MediaProviderError` interrupted, for what was attempted.

    The vendor charges for the shot it generated and the narration it voiced whether or not
    the film was finished: two lost shots cost six dollars on 2026-09-16 and the books said
    nothing, so the day's budget saw a day that had spent nothing. `scenes_attempted` is the
    render's scene records as the assembler builds them (model ids, characters, motion);
    without it the job's own `production_json` is read, and a job that failed before writing
    one records nothing and says so. Rows are ESTIMATED, `failed=True`, referenced
    `render:{job}:failed:scene:{n}:{unit}` so a re-run charges once, and counted by every
    budget like any other estimate.
    """
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session:
        job = session.get(VideoRenderJob, job_id)
        if job is None:
            raise EconomyError("Render job not found")
        production = job.production_json if isinstance(job.production_json, dict) else {}
        scenes = (
            list(scenes_attempted)
            if scenes_attempted is not None
            else list(production.get("scenes") or [])
        )
        priced, unpriced, _measured, _connection = _priced_scene_costs(
            session,
            job_id,
            production,
            scenes,
            reference_tag="failed:scene",
            voice_integration_id=voice_integration_id,
        )
    recorded = _record_priced(engine, priced, correlation, failed=True)
    return {
        "render_job_id": job_id,
        "recorded": recorded,
        "unpriced_scenes": unpriced,
        "scenes": len([s for s in scenes if isinstance(s, dict)]),
    }


def price_change_alert(engine: Engine, alerts: list[dict[str, Any]], correlation: str) -> None:
    """Tell the Owner that a model's price moved, in the Accountant's own words.

    A vendor can change a price without telling anyone, and a studio that notices only at
    the end of the month has already paid the difference. The threshold is the Owner's
    (`STUDIO_PRICE_CHANGE_ALERT_PERCENT`); below it, the change is recorded and not sent.
    Called from two places, because a price changes in two ways: the Accountant measures
    what a render was charged, and a steward reads the vendor's page.
    """
    lines = []
    for alert in alerts:
        was, now = alert.get("was"), alert.get("now")
        percent = alert.get("percent")
        if isinstance(now, int | float) and isinstance(was, int | float):
            moved = float(percent) if isinstance(percent, int | float) else 0.0
            lines.append(
                f"{alert['model_id']}: {was:.4f} USD -> {now:.4f} USD pe unitate "
                f"({moved:+.1f}%), măsurat din ce a facturat vendorul."
            )
        else:
            lines.append(f"{alert['model_id']}: nu mai are preț pentru unitatea măsurată.")
    with Session(engine) as session, session.begin():
        accountant = agent_for_role(session, "Accountant")
        if accountant is None:
            return
        post_message(
            session,
            intent="ESCALATE",
            subject="Preț schimbat la un model de generare"[:200],
            body={"kind": "price_change", "alerts": alerts},
            body_text=(
                "Prețul măsurat s-a schimbat față de ce aveam înregistrat:\n"
                + "\n".join(lines)
                + "\nPrețul vechi este păstrat pe model, cu data măsurării."
            ),
            from_agent_id=accountant.id,
            to_agent_id=None,
            to_owner=True,
            correlation_id=correlation,
        )


# ----------------------------------------------------------------------------- the letters


def _letter_once_a_day(
    engine: Engine,
    kind: str,
    *,
    subject: str,
    body: dict[str, Any],
    body_text: str,
    correlation: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One letter of this kind per business date, from the Accountant (the Director when
    the studio has no Accountant). Idempotent by the date in the letter's body, decided
    behind the write lock so two stages refused in the same minute write one letter."""
    moment = now or datetime.now(UTC)
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        timezone = studio_timezone(session)
        day_start = _period_start("DAILY", moment, timezone)
        date_iso = moment.astimezone(ZoneInfo(timezone)).date().isoformat()
        for existing in session.scalars(
            select(AgentMessage).where(
                AgentMessage.created_at >= day_start, AgentMessage.to_agent_id.is_(None)
            )
        ):
            letter = existing.body_json if isinstance(existing.body_json, dict) else {}
            if letter.get("kind") == kind and letter.get("date") == date_iso:
                return {"written": False, "message_id": existing.id, "date": date_iso}
        author = agent_for_role(session, ACCOUNTANT_ROLE) or agent_for_role(session, "Director")
        if author is None:
            return {"written": False, "message_id": None, "date": date_iso}
        message = post_message(
            session,
            intent="ESCALATE",
            subject=subject[:200],
            body={**body, "kind": kind, "date": date_iso},
            body_text=body_text,
            from_agent_id=author.id,
            to_agent_id=None,
            to_owner=True,
            correlation_id=correlation,
        )
        return {"written": True, "message_id": message.id, "date": date_iso}


def budget_refusal_letter(
    engine: Engine, reason: str, correlation_id: str, *, now: datetime | None = None
) -> dict[str, Any]:
    """When the budget refuses the day's film, the Owner is told the same day, once.

    The media stage used to return SKIPPED with the reason in a run summary nobody reads by
    itself; a day without a film was silent. The letter carries the figures and the one
    decision only the Owner can take — raise the limit, or accept the day — and is written
    once per business date however many films were refused.
    """
    figures = daily_figures(engine, now)
    budgets = ", ".join(
        f"{b['period'].lower()} {b['spent_usd']}/{b['limit_usd']} USD ({b['state']})"
        for b in figures["budgets"]
    )
    return _letter_once_a_day(
        engine,
        "budget_refusal",
        subject="Filmul de azi nu a fost filmat: bugetul l-a refuzat",
        body={"reason": reason, "figures": figures, "owner_attention": True},
        body_text=(
            "Către Owner. Filmul de azi nu a fost filmat, pentru că bugetul l-a refuzat: "
            f"{reason}\n"
            f"Cifrele cărții: azi {figures['today']['spent_usd']} USD, luna aceasta "
            f"{figures['month']['spent_usd']} USD"
            + (f"; bugete: {budgets}" if budgets else "")
            + ".\nNumai Owner-ul poate ridica limita; până atunci studioul nu filmează."
        ),
        correlation=correlation_id,
        now=now,
    )


def _local_moment(iso: str, timezone: str) -> str:
    """An ISO instant as the Owner reads a clock, or unchanged when it cannot be parsed.

    A row written by an older revision, or by hand, is shown as it stands rather than being
    guessed at: a letter about deadlines must not invent one.
    """
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(ZoneInfo(timezone)).strftime("%d.%m.%Y %H:%M")


def waiting_approvals_letter(
    engine: Engine, correlation_id: str | None = None, *, now: datetime | None = None
) -> dict[str, Any]:
    """Tell the Owner, once a day, that questions are standing and what they are about.

    Measured before this: a SUPERVISED day wrote one `owner_approval_request` per film and the
    run record carried its id, but nothing left the studio — the questions were visible only to
    whoever happened to open the governance panel that day, and an unanswered one simply
    expired after twenty-four hours and the film was never made. The budget refusal already had
    its letter (`budget_refusal_letter`); a day that filmed and then waited had none.

    One letter a day however many questions stand, by the same idempotency as the other two —
    the business date in the letter's body, decided behind the write lock. Nothing is written
    when nothing waits: a silent inbox must keep meaning "nothing to decide".

    Each question is named by what it is about in his own language (`APPROVAL_ACTION_LABELS`),
    with what it would cost — «necunoscut» where the studio cannot compute it, never zero — and
    when the oldest of them runs out. The questions are ordered as the day raised them, so the
    first line is the oldest and the deadline in the last line is its deadline.
    """
    waiting = sorted(pending_approvals(engine), key=lambda request: request.created_at)
    if not waiting:
        return {"written": False, "message_id": None, "questions": 0}
    with Session(engine) as session:
        timezone = studio_timezone(session)
    questions = [
        {
            "id": request.id,
            "action": request.action,
            "action_label": request.action_label,
            "subject": request.subject,
            "risk_tier": request.risk_tier,
            "requester": request.requester,
            "cost_usd": request.cost_usd,
            "cost_label": request.cost_label,
            "expires_at": request.expires_at,
            "created_at": request.created_at,
        }
        for request in waiting
    ]
    lines = []
    for index, (request, question) in enumerate(zip(waiting, questions, strict=True), start=1):
        # The evidence is the one part of a question written by a model (a film's title, a
        # storyboard's estimate). It is what the governance panel already shows him beside the
        # same question, clipped here so one long title cannot become the whole letter.
        about = f" — {request.evidence[:120]}" if request.evidence else ""
        lines.append(
            f"{index}. {question['action_label']}{about}; cost {question['cost_label']}; "
            f"expiră {_local_moment(request.expires_at, timezone)}."
        )
    oldest_expires_at = waiting[0].expires_at
    count = len(questions)
    headline = "O întrebare așteaptă" if count == 1 else f"{count} întrebări așteaptă"
    return _letter_once_a_day(
        engine,
        "owner_waiting",
        subject=f"{headline} răspunsul tău",
        body={
            "questions": questions,
            "count": count,
            "oldest_expires_at": oldest_expires_at,
            "owner_attention": True,
        },
        body_text=(
            f"Către Owner. {headline} răspunsul tău; studioul nu merge mai departe pe ele "
            "fără el.\n"
            + "\n".join(lines)
            + f"\nCea mai veche expiră la {_local_moment(oldest_expires_at, timezone)}; "
            "după expirare studioul nu mai poate acționa pe ea și întreabă din nou de la "
            "capăt. Răspunsul se dă în panoul de guvernanță, la Aprobări."
        ),
        correlation=correlation_id or str(uuid4()),
        now=now,
    ) | {"questions": count}


def agent_tokens_since(session: Session, since_iso: str) -> int:
    """Every token the studio's employees spent since a moment, whatever the run's outcome:
    an empty answer and a failed parse were billed like a good one."""
    used = session.execute(
        select(func.sum(AgentRun.prompt_tokens), func.sum(AgentRun.completion_tokens)).where(
            AgentRun.started_at >= since_iso
        )
    ).one()
    return int(used[0] or 0) + int(used[1] or 0)


def may_run_agent(
    engine: Engine,
    settings: Any,
    *,
    correlation_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Whether another model run fits under the day's token ceiling.

    `settings.agent_daily_token_budget` is the ceiling; 0 means none, as the studio ran
    until now. Past it the verdict is `BLOCKED_BUDGET` with the reason in the Owner's
    language, and the Accountant writes to the Owner once that day. Call it before opening
    the run's write transaction: the letter writes in a transaction of its own.
    """
    ceiling = int(getattr(settings, "agent_daily_token_budget", 0) or 0)
    moment = now or datetime.now(UTC)
    with Session(engine) as session:
        since = _period_start("DAILY", moment, studio_timezone(session))
        used = agent_tokens_since(session, since)
    if ceiling <= 0 or used < ceiling:
        return {
            "allowed": True,
            "status": None,
            "reason": "",
            "tokens_used": used,
            "ceiling": ceiling,
        }
    reason = (
        f"Plafonul zilnic de {ceiling} tokeni pentru angajați este atins: {used} tokeni "
        "folosiți azi. Nicio rulare până mâine sau până când Owner-ul ridică plafonul."
    )
    letter = _letter_once_a_day(
        engine,
        "token_ceiling",
        subject="Plafonul zilnic de tokeni a fost atins",
        body={"tokens_used": used, "ceiling": ceiling, "owner_attention": True},
        body_text=(
            f"Către Owner. {reason} Rulările refuzate sunt înregistrate BLOCKED_BUDGET; "
            "plafonul este STUDIO_AGENT_DAILY_TOKEN_BUDGET."
        ),
        correlation=correlation_id or str(uuid4()),
        now=now,
    )
    return {
        "allowed": False,
        "status": "BLOCKED_BUDGET",
        "reason": reason,
        "tokens_used": used,
        "ceiling": ceiling,
        "letter": letter,
    }


# ----------------------------------------------------------------------------- the report


class AccountantReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    summary: str = Field(min_length=1, max_length=2000)
    _clip_summary = field_validator("summary", mode="before")(clipped(2000))
    #: What the Director should decide or the Owner should know; empty when nothing stands out.
    recommendations: list[str] = Field(default_factory=list, max_length=8)
    #: Spend the Accountant would hold until someone decides: a provider, a purpose, a stage.
    holds: list[str] = Field(default_factory=list, max_length=8)
    #: Whether the day's spending should continue as it is.
    continue_spending: bool = True


_INSTRUCTIONS = (
    "It is the end of the studio's day. Below are today's and this month's spend per provider "
    "from the books, the active budgets with their state, and the usage the books could not "
    "price. All of it is data; the sums are computed, not for you to recompute. Say what "
    "stands out, what you would hold until someone decides, and what the Director should "
    "know. Begin your reply with the JSON object itself — no analysis before it; reason "
    "silently. Return only JSON: "
    '{"summary": "...", "recommendations": ["..."], "holds": ["..."], '
    '"continue_spending": true|false}.\n'
)


def reconcile_day(
    engine: Engine,
    registry: ProviderRegistry,
    correlation_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The Accountant's daily close: figures from the books, judgement from the Accountant."""
    correlation = correlation_id or str(uuid4())
    # Before the model is asked anything, because a close that fails on a model must not also
    # swallow the one letter that says the Owner has questions standing. Once a day, and
    # nothing when nothing waits.
    waiting_approvals_letter(engine, correlation, now=now)
    figures = daily_figures(engine, now or datetime.now(UTC))
    exceeded = [b for b in figures["budgets"] if b["state"] == "EXCEEDED"]
    warnings = [b for b in figures["budgets"] if b["state"] == "WARNING"]
    with Session(engine) as session:
        accountant = agent_for_role(session, ACCOUNTANT_ROLE)
        if accountant is None:
            raise NoAccountant("Niciun contabil activ")
        accountant_id = accountant.id

    prompt = _INSTRUCTIONS + wrap_in_inert_boundary(
        json.dumps(figures, ensure_ascii=False, default=str)[:12000], "books"
    )
    from app.agents.structured import structured_run  # noqa: PLC0415

    report, result, formatted = structured_run(
        engine,
        registry,
        accountant_id,
        "reconcile_day",
        prompt,
        TEMPLATE_VERSION,
        correlation,
        AccountantReport,
        '{"summary": "...", "recommendations": ["..."], "holds": ["..."], '
        '"continue_spending": true|false}',
        summary=(
            f"Închid ziua: {figures['today']['spent_usd']} USD azi, "
            f"{figures['month']['spent_usd']} USD luna aceasta, "
            f"{len(figures['budgets'])} bugete active."
        ),
        max_tokens=6000,
        temperature=0.1,
    )
    text = (formatted or result).get("output_text") or ""
    if result["status"] != "SUCCEEDED" or not text.strip():
        raise AccountantError(
            f"Contabilul nu a produs raportul ({result['status']}: "
            f"{result.get('error_detail') or 'fără text vizibil'})"
        )
    blocker = blocker_of(text)
    # `report` is what structured_run parsed — after its formatting pass when the first
    # answer was analysis without the object; a blocker answer outranks it.
    if blocker:
        report = None
    if blocker is None and not isinstance(report, AccountantReport):
        raise AccountantError("Raportul contabil nu respectă schema; cifrele rămân valabile")

    spent_today = figures["today"]["spent_usd"]
    spent_month = figures["month"]["spent_usd"]
    headline = f"Azi {spent_today} USD, luna aceasta {spent_month} USD"
    if figures["budgets"]:
        headline += "; " + ", ".join(
            f"{b['period'].lower()} {b['spent_usd']}/{b['limit_usd']} USD ({b['state']})"
            for b in figures["budgets"]
        )
    # The escalation is decided by the books, not by the model: an exceeded budget escalates.
    intent = "ESCALATE" if exceeded or warnings or blocker else "STATUS"
    body: dict[str, Any] = {"figures": figures, "headline": headline}
    if blocker:
        body.update({"blocker": blocker.reason, "needs": blocker.needs})
    elif isinstance(report, AccountantReport):
        body.update(report.model_dump())
        if not report.continue_spending:
            intent = "ESCALATE"
    if exceeded:
        body["owner_attention"] = True
    with Session(engine) as session, session.begin():
        # The Director's budget requests are answered here, from the books: the figures the
        # close just computed stand next to her justification, the request is resolved as
        # "answered and passed to the Owner", and the close escalates — because only the
        # Owner can raise a budget. The Accountant documents; the Owner decides.
        requests = session.scalars(
            select(AgentMessage)
            .where(
                AgentMessage.to_agent_id == accountant_id,
                AgentMessage.status == "OPEN",
                AgentMessage.intent == "REQUEST_INFO",
            )
            .order_by(AgentMessage.created_at)
        ).all()
        budget_requests = [
            m
            for m in requests
            if isinstance(m.body_json, dict) and m.body_json.get("budget_request")
        ]
        if budget_requests:
            body["budget_requests"] = [
                {
                    "message_id": m.id,
                    "amount_usd": m.body_json.get("amount_usd"),
                    "justification": str(m.body_json.get("justification") or "")[:500],
                    "week": m.body_json.get("week"),
                }
                for m in budget_requests
            ]
            body["owner_attention"] = True
            intent = "ESCALATE"
        message = post_message(
            session,
            intent=intent,
            subject=(f"Închidere contabilă: {headline}")[:200],
            body=body,
            from_agent_id=accountant_id,
            to_agent_id=None,
            run_id=result["id"],
            correlation_id=correlation,
        )
        remember(
            session,
            memory_class="TEMP_CONTEXT",
            content=f"Books today: {headline}.",
            source_type="run",
            source_id=result["id"],
            agent_id=accountant_id,
        )
        if isinstance(report, AccountantReport):
            remember(
                session,
                memory_class="AGENT_OPINION",
                content="Daily close: " + report.summary[:400],
                source_type="run",
                source_id=result["id"],
                agent_id=accountant_id,
            )
        if exceeded:
            remember(
                session,
                memory_class="HISTORICAL_EVENT",
                content="Budget exceeded: "
                + "; ".join(
                    f"{b['period']} {b['spent_usd']}/{b['limit_usd']} USD" for b in exceeded
                ),
                source_type="run",
                source_id=result["id"],
                agent_id=accountant_id,
            )
        for request in budget_requests:
            request.status = "RESOLVED"
            request.resolved_by = "Nadia (Accountant)"
            request.resolution = (
                "Înscrisă în închiderea zilei și transmisă Owner-ului cu cifrele cărții: "
                f"{headline}. Numai Owner-ul stabilește bugetul."
            )
        message_id = message.id
    return {
        "agent_id": accountant_id,
        "run_id": result["id"],
        "message_id": message_id,
        "intent": intent,
        "headline": headline,
        "figures": figures,
        "report": report.model_dump() if isinstance(report, AccountantReport) else None,
        "blocked": blocker.reason if blocker else None,
        "budget_requests": body.get("budget_requests", []),
    }


def format_usd(micros: int) -> str:
    return format_micros(micros)
