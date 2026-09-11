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
narration at the stored per-character price of the model that voiced it. Usage with no stored
price is reported as unpriced, never as free.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.agents.identity import blocker_of, parse_structured
from app.agents.memory import agent_for_role, remember
from app.agents.messages import post_message
from app.agents.services import run_agent_task
from app.economy.budget import budget_status
from app.economy.services import EconomyError, format_micros, record_provider_cost
from app.factual.sanitizer import wrap_in_inert_boundary
from app.integrations.models import Integration
from app.media.models import VideoRenderJob
from app.media.production_policy import estimate_cost_usd
from app.providers.registry import ProviderRegistry

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


def record_render_costs(
    engine: Engine, render_job_id: str, correlation_id: str | None = None
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
        priced: list[dict[str, Any]] = []
        unpriced = 0
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            integration_id = scene.get("integration_id") or (
                (production.get("voice") or {}).get("integration_id")
            )
            model_id = scene.get("model_id")
            characters = int(scene.get("characters") or 0)
            if not integration_id or not model_id or not characters:
                continue
            estimate = estimate_cost_usd(session, integration_id, model_id, characters)
            if estimate is None or estimate <= 0:
                unpriced += 1
                continue
            integration = session.get(Integration, integration_id)
            priced.append(
                {
                    "provider": integration.kind if integration else "unknown",
                    "reference": f"render:{render_job_id}:scene:{scene.get('scene_index')}",
                    "amount": f"{estimate:.6f}",
                    "attribution": {
                        "render_job_id": render_job_id,
                        "scene_index": scene.get("scene_index"),
                        "model_id": model_id,
                        "characters": characters,
                    },
                }
            )
    recorded = 0
    for item in priced:
        try:
            record_provider_cost(
                engine,
                provider=item["provider"],
                external_reference=item["reference"],
                status="ESTIMATED",
                amount=item["amount"],
                attribution=item["attribution"],
                correlation_id=correlation,
            )
            recorded += 1
        except EconomyError:
            # Already recorded for this scene: the day was re-run, and one scene costs once.
            continue
    return {"render_job_id": render_job_id, "recorded": recorded, "unpriced_scenes": unpriced}


# ----------------------------------------------------------------------------- the report


class AccountantReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    summary: str = Field(min_length=1, max_length=2000)
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
    "know. Return only JSON: "
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
    result = run_agent_task(
        engine,
        registry,
        accountant_id,
        "reconcile_day",
        prompt,
        TEMPLATE_VERSION,
        correlation,
        summary=(
            f"Închid ziua: {figures['today']['spent_usd']} USD azi, "
            f"{figures['month']['spent_usd']} USD luna aceasta, "
            f"{len(figures['budgets'])} bugete active."
        ),
        max_tokens=1200,
        temperature=0.1,
        emit_message=False,
    )
    text = result.get("output_text") or ""
    if result["status"] != "SUCCEEDED" or not text.strip():
        raise AccountantError(
            f"Contabilul nu a produs raportul ({result['status']}: "
            f"{result.get('error_detail') or 'fără text vizibil'})"
        )
    blocker = blocker_of(text)
    report = None if blocker else parse_structured(text, AccountantReport)
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
    }


def format_usd(micros: int) -> str:
    return format_micros(micros)
