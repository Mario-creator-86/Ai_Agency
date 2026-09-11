"""How much the studio may spend, and whether it still may.

The books say what was spent; the treasury says what is spendable. Neither says what the
Owner allows, so no stage could refuse a render that would blow the month, and the
Accountant had nothing to report against. A `SpendingBudget` is that allowance: one active
limit per period, set by the Owner, in USD micros like every amount in the books. Spend is
measured from `provider_cost_record` — ESTIMATED and BILLED alike, because an estimate is a
commitment the studio already made, and a budget that counted only invoices would report
"fine" until the invoices arrived. Unpriced usage (a model without a stored price) cannot be
counted; it is reported as such rather than as zero.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.agents.models import AgentRun
from app.economy.models import ProviderCostRecord, SpendingBudget
from app.economy.services import EconomyError, format_micros, to_micros
from app.services import append_event, utc_now

PERIODS = ("DAILY", "MONTHLY")


class BudgetCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: str = Field(pattern="^(DAILY|MONTHLY)$")
    #: The limit in USD, as a decimal string; "0" or "" retires the active budget.
    limit_usd: str = Field(max_length=20)
    warn_ratio: float = Field(default=0.8, ge=0.1, le=1.0)
    notes: str | None = Field(default=None, max_length=2000)


def _period_start(period: str, now: datetime) -> str:
    if period == "DAILY":
        return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def _budget_view(row: SpendingBudget) -> dict[str, Any]:
    return {
        "id": row.id,
        "period": row.period,
        "limit_usd": format_micros(row.limit_usd_micros),
        "limit_usd_micros": row.limit_usd_micros,
        "warn_ratio": row.warn_ratio,
        "active": bool(row.active),
        "set_by": row.set_by,
        "notes": row.notes,
        "created_at": row.created_at,
        "replaced_at": row.replaced_at,
    }


def set_budget(
    engine: Engine,
    command: BudgetCommand,
    *,
    set_by: str = "owner",
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Set (or retire) the active budget for a period. The previous one is kept, replaced."""
    correlation = correlation_id or str(uuid4())
    limit_micros = to_micros(command.limit_usd or "0") if (command.limit_usd or "").strip() else 0
    if limit_micros < 0:
        raise EconomyError("A budget cannot be negative.")
    with Session(engine) as session, session.begin():
        now = utc_now()
        for previous in session.scalars(
            select(SpendingBudget).where(
                SpendingBudget.period == command.period, SpendingBudget.active.is_(True)
            )
        ):
            previous.active = False
            previous.replaced_at = now
        if limit_micros == 0:
            append_event(
                session,
                "economy.budget_retired",
                "spending_budget",
                command.period,
                1,
                {"period": command.period, "set_by": set_by},
                correlation,
            )
            return {"period": command.period, "active": False}
        row = SpendingBudget(
            id=str(uuid4()),
            period=command.period,
            limit_usd_micros=limit_micros,
            warn_ratio=command.warn_ratio,
            active=True,
            set_by=set_by[:100],
            notes=(command.notes or "").strip()[:2000] or None,
            created_at=now,
        )
        session.add(row)
        session.flush()
        event = append_event(
            session,
            "economy.budget_set",
            "spending_budget",
            row.id,
            1,
            {"period": row.period, "limit_usd": format_micros(limit_micros), "set_by": set_by},
            correlation,
        )
        row.event_id = event.event_id
        return _budget_view(row)


def spend_since(session: Session, since_iso: str) -> dict[str, Any]:
    """What the books say was spent since a moment: priced costs, and the usage nobody priced."""
    rows = session.execute(
        select(
            ProviderCostRecord.provider,
            ProviderCostRecord.status,
            func.sum(ProviderCostRecord.usd_micros),
            func.count(),
        )
        .where(ProviderCostRecord.recorded_at >= since_iso)
        .group_by(ProviderCostRecord.provider, ProviderCostRecord.status)
    ).all()
    by_provider: dict[str, dict[str, Any]] = {}
    total = 0
    for provider, status, micros, count in rows:
        entry = by_provider.setdefault(
            provider,
            {"provider": provider, "estimated_usd_micros": 0, "billed_usd_micros": 0, "records": 0},
        )
        key = "billed_usd_micros" if status == "BILLED" else "estimated_usd_micros"
        entry[key] += int(micros or 0)
        entry["records"] += int(count or 0)
        total += int(micros or 0)
    runs = session.execute(
        select(
            func.count(), func.sum(AgentRun.prompt_tokens), func.sum(AgentRun.completion_tokens)
        ).where(AgentRun.started_at >= since_iso, AgentRun.status == "SUCCEEDED")
    ).one()
    unpriced_runs = session.scalar(
        select(func.count()).where(
            AgentRun.started_at >= since_iso,
            AgentRun.status == "SUCCEEDED",
            AgentRun.cost_vr.is_(None),
        )
    )
    return {
        "since": since_iso,
        "spent_usd_micros": total,
        "spent_usd": format_micros(total),
        "by_provider": sorted(by_provider.values(), key=lambda e: e["provider"]),
        "agent_runs": int(runs[0] or 0),
        "prompt_tokens": int(runs[1] or 0),
        "completion_tokens": int(runs[2] or 0),
        # Runs whose model has no stored price: real usage the books cannot value yet.
        "unpriced_agent_runs": int(unpriced_runs or 0),
    }


def budget_status(engine: Engine, now: datetime | None = None) -> dict[str, Any]:
    """Every active budget against the spend of its period, plus the spend itself."""
    moment = now or datetime.now(UTC)
    with Session(engine) as session:
        budgets = session.scalars(
            select(SpendingBudget).where(SpendingBudget.active.is_(True))
        ).all()
        periods = []
        for row in budgets:
            since = _period_start(row.period, moment)
            spend = spend_since(session, since)
            spent = spend["spent_usd_micros"]
            ratio = spent / row.limit_usd_micros if row.limit_usd_micros else 0.0
            periods.append(
                {
                    **_budget_view(row),
                    "spent_usd": format_micros(spent),
                    "spent_usd_micros": spent,
                    "remaining_usd": format_micros(max(0, row.limit_usd_micros - spent)),
                    "remaining_usd_micros": row.limit_usd_micros - spent,
                    "ratio": round(ratio, 4),
                    "state": (
                        "EXCEEDED"
                        if spent > row.limit_usd_micros
                        else "WARNING"
                        if ratio >= row.warn_ratio
                        else "OK"
                    ),
                    "unpriced_agent_runs": spend["unpriced_agent_runs"],
                }
            )
        today = spend_since(session, _period_start("DAILY", moment))
        month = spend_since(session, _period_start("MONTHLY", moment))
    return {"budgets": periods, "today": today, "month": month, "measured_at": utc_now()}


def may_spend(engine: Engine, usd_micros: int, now: datetime | None = None) -> dict[str, Any]:
    """Whether a spend of this size fits every active budget; with no budget, it always does.

    An estimate of zero (unpriced) still has to pass: a budget already exceeded refuses even
    what it cannot value, because it cannot value it.
    """
    status = budget_status(engine, now)
    for period in status["budgets"]:
        if period["spent_usd_micros"] + max(0, usd_micros) > period["limit_usd_micros"]:
            return {
                "allowed": False,
                "period": period["period"],
                "reason": (
                    f"Bugetul {period['period'].lower()} de {period['limit_usd']} USD ar fi "
                    f"depășit: {period['spent_usd']} USD cheltuiți deja, cererea este de "
                    f"{format_micros(max(0, usd_micros))} USD."
                ),
                "status": status,
            }
    return {"allowed": True, "period": None, "reason": "", "status": status}
