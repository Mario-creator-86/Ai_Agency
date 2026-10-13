"""The books as they stood at past moments: the Treasury's balance, the day's spend and tokens.

The headquarters' «Reluarea zilei» plays a finished run back from its events. Its walls showed
«—» for the Treasury and the tokens plate, because the live books are not the books of that
night and the events do not carry the figures. The figures are in the books' own rows, each with
its moment: a ledger posting's `posted_at`, a provider cost's `recorded_at` (and the moment an
invoice replaced it), an agent run's start and finish with its tokens and price, a spend hold's
`reserved_at` and `released_at`, a budget's `created_at` and `replaced_at`. Read up to a moment,
they say what the live read (`treasury_snapshot`, `budget_status`) said then, by the same rules:

* the spendable balance is the VR_CASH class of the postings made by then;
* a period's spend is every provider cost recorded in it by then that no invoice had yet
  replaced, and the price of every agent run in it that had finished by then, if the books
  held it then (a run priced later carries `priced_after.at`); a hold counts while it was
  held; the budget is the one that was active then;
* the day's tokens are those of the runs that had finished by then (a run's tokens are known
  when it finishes).

What these rows cannot say is not reconstructed: the evidence and estimates that were pending
then (their status changes in place), so a reading carries the spendable balance and the money
classes of the ledger, not the pending and forecast lines.

A replay crosses many moments, so one call answers all of them, with a fixed number of indexed
queries whatever their number; the moments are compared in Python.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.agents.models import AgentRun
from app.economy.budget import _period_start, studio_timezone
from app.economy.models import (
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
    ProviderCostRecord,
    SpendingBudget,
    SpendReservation,
)
from app.economy.services import EconomyError, format_micros, to_micros
from app.services import read_instant

#: The most moments one call answers: a day's run crosses about fifty.
MAX_MOMENTS = 240

MONEY_CLASSES = ("VR_CASH", "VR_RESTRICTED", "VR_RECEIVABLE", "VR_DEBT")

NOTE = (
    "Soldurile și cheltuielile din registrul studioului la fiecare moment cerut. Sumele în "
    "așteptare și estimările de atunci nu sunt reconstituite."
)


def _moment(value: str | None) -> datetime | None:
    """A stored stamp as an instant; None for an empty or unreadable one."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(read_instant(value))
    except ValueError:
        return None


def _within(stamp: datetime | None, since: datetime, at: datetime) -> bool:
    return stamp is not None and since <= stamp <= at


def _still(stamp: datetime | None, at: datetime) -> bool:
    """Not yet happened at `at`: an empty stamp, or one after it."""
    return stamp is None or stamp > at


def economy_as_of(engine: Engine, moments: Sequence[str]) -> dict[str, Any]:
    """The Treasury's balance and the day's budget, spend and tokens at each moment asked.

    `moments` are instants (ISO 8601); each is answered in the order asked, as UTC. Raises
    ValueError for an instant that is not one, for none and for more than MAX_MOMENTS.
    """
    ats = [read_instant(value) for value in moments]
    if not ats:
        raise ValueError("at least one moment is needed")
    if len(ats) > MAX_MOMENTS:
        raise ValueError(f"at most {MAX_MOMENTS} moments")
    instants = [datetime.fromisoformat(at) for at in ats]
    first = min(instants).isoformat()
    last = max(instants).isoformat()
    with Session(engine) as session:
        timezone = studio_timezone(session)
        accounts = {a.code: a for a in session.scalars(select(LedgerAccount)).all()}
        # The ledger up to the first moment, summed per account; its postings after it, one by one.
        base = session.execute(
            select(
                LedgerEntry.account_code,
                func.sum(LedgerEntry.debit_micros),
                func.sum(LedgerEntry.credit_micros),
            )
            .where(
                LedgerEntry.transaction_id.in_(
                    select(LedgerTransaction.id).where(LedgerTransaction.posted_at <= first)
                )
            )
            .group_by(LedgerEntry.account_code)
        ).all()
        later = session.execute(
            select(
                LedgerTransaction.posted_at,
                LedgerEntry.account_code,
                LedgerEntry.debit_micros,
                LedgerEntry.credit_micros,
            )
            .select_from(LedgerTransaction)
            .join(LedgerEntry, LedgerEntry.transaction_id == LedgerTransaction.id)
            .where(LedgerTransaction.posted_at > first, LedgerTransaction.posted_at <= last)
        ).all()
        budgets = session.scalars(
            select(SpendingBudget).where(SpendingBudget.created_at <= last)
        ).all()
        periods = {"DAILY", *(b.period for b in budgets)}
        window = min(
            datetime.fromisoformat(_period_start(period, moment, timezone))
            for period in periods
            for moment in instants
        ).isoformat()
        # Every status the table allows, so its (status, recorded_at) index serves the range.
        costs = session.execute(
            select(
                ProviderCostRecord.recorded_at,
                ProviderCostRecord.usd_micros,
                ProviderCostRecord.reconciled_at,
            ).where(
                ProviderCostRecord.status.in_(("ESTIMATED", "BILLED")),
                ProviderCostRecord.recorded_at >= window,
                ProviderCostRecord.recorded_at <= last,
            )
        ).all()
        runs = session.execute(
            select(
                AgentRun.started_at,
                AgentRun.finished_at,
                AgentRun.status,
                AgentRun.cost_vr,
                AgentRun.prompt_tokens,
                AgentRun.completion_tokens,
                AgentRun.context_json,
            ).where(AgentRun.started_at >= window, AgentRun.started_at <= last)
        ).all()
        holds = session.execute(
            select(
                SpendReservation.reserved_at,
                SpendReservation.released_at,
                SpendReservation.usd_micros,
            ).where(
                SpendReservation.status.in_(("RESERVED", "RELEASED", "SETTLED")),
                SpendReservation.reserved_at >= window,
                SpendReservation.reserved_at <= last,
            )
        ).all()

    base_totals = {code: (int(debit or 0), int(credit or 0)) for code, debit, credit in base}
    postings = [(_moment(at), code, int(d or 0), int(c or 0)) for at, code, d, c in later]
    cost_rows = [(_moment(r), int(usd or 0), _moment(rec)) for r, usd, rec in costs]
    run_rows = []
    for started, finished, status, cost_vr, prompt, completion, context in runs:
        try:
            price = to_micros(cost_vr) if cost_vr is not None else None
        except EconomyError:
            price = None  # a malformed string is not money, as in the live budget
        # A cost given after the run (the Director's re-pricing at the price active later,
        # 2026-10-11, stamps when): the books did not know it before that moment, so the
        # replay keeps the run unpriced until then.
        late = context.get("priced_after") if isinstance(context, dict) else None
        priced_at = _moment(str(late.get("at") or "")) if isinstance(late, dict) else None
        run_rows.append(
            (
                _moment(started),
                _moment(finished),
                status,
                cost_vr,
                price,
                prompt,
                completion,
                priced_at,
            )
        )
    hold_rows = [(_moment(r), _moment(rel), int(usd or 0)) for r, rel, usd in holds]
    budget_rows = [(b, _moment(b.created_at), _moment(b.replaced_at)) for b in budgets]

    def treasury(at: datetime) -> dict[str, Any]:
        totals = dict(base_totals)
        for when, code, debit, credit in postings:
            if when is not None and when <= at:
                d, c = totals.get(code, (0, 0))
                totals[code] = (d + debit, c + credit)
        by_class: dict[str, int] = {}
        for code, (debit, credit) in totals.items():
            account = accounts.get(code)
            if account is None or not account.money_class:
                continue
            balance = debit - credit if account.normal_balance == "DEBIT" else credit - debit
            by_class[account.money_class] = by_class.get(account.money_class, 0) + balance
        spendable = by_class.get("VR_CASH", 0)
        return {
            "unit": "VR$",
            "spendable": {
                "money_class": "VR_CASH",
                "label": "VR VIRTUAL",
                "amount": format_micros(spendable),
                "spendable": True,
            },
            "positions": [
                {
                    "money_class": money_class,
                    "label": "VR VIRTUAL",
                    "amount": format_micros(by_class.get(money_class, 0)),
                    "spendable": money_class == "VR_CASH",
                }
                for money_class in MONEY_CLASSES
            ],
            "in_deficit": spendable < 0,
        }

    def spend(since: datetime, at: datetime) -> dict[str, Any]:
        costs_micros = sum(
            usd
            for when, usd, replaced in cost_rows
            if _within(when, since, at) and _still(replaced, at)
        )
        done = [
            row
            for row in run_rows
            if _within(row[0], since, at) and row[1] is not None and row[1] <= at
        ]

        def known(row: tuple[Any, ...]) -> bool:
            """Whether the run's price was in the books at `at`."""
            return row[3] is not None and (row[7] is None or row[7] <= at)

        agent_micros = sum(row[4] or 0 for row in done if known(row))
        succeeded = [row for row in done if row[2] == "SUCCEEDED"]
        reserved = sum(
            usd
            for held, released, usd in hold_rows
            if _within(held, since, at) and _still(released, at)
        )
        total = costs_micros + agent_micros
        return {
            "since": since.isoformat(),
            "spent_usd_micros": total,
            "spent_usd": format_micros(total),
            "agent_usd_micros": agent_micros,
            "agent_usd": format_micros(agent_micros),
            "reserved_usd_micros": reserved,
            "reserved_usd": format_micros(reserved),
            "agent_runs": len(succeeded),
            "prompt_tokens": sum(int(row[5] or 0) for row in succeeded),
            "completion_tokens": sum(int(row[6] or 0) for row in succeeded),
            "unpriced_agent_runs": sum(1 for row in succeeded if not known(row)),
        }

    def budget(at: datetime) -> dict[str, Any]:
        periods_now = []
        for row, created, replaced in budget_rows:
            if created is None or created > at or not _still(replaced, at):
                continue
            since = datetime.fromisoformat(_period_start(row.period, at, timezone))
            used = spend(since, at)
            committed = used["spent_usd_micros"] + used["reserved_usd_micros"]
            limit = row.limit_usd_micros
            ratio = committed / limit if limit else 0.0
            periods_now.append(
                {
                    "id": row.id,
                    "period": row.period,
                    "limit_usd": format_micros(limit),
                    "limit_usd_micros": limit,
                    "warn_ratio": row.warn_ratio,
                    "active": True,
                    "since": used["since"],
                    "spent_usd": used["spent_usd"],
                    "spent_usd_micros": used["spent_usd_micros"],
                    "reserved_usd": used["reserved_usd"],
                    "reserved_usd_micros": used["reserved_usd_micros"],
                    "remaining_usd": format_micros(max(0, limit - committed)),
                    "remaining_usd_micros": limit - committed,
                    "ratio": round(ratio, 4),
                    "state": (
                        "EXCEEDED"
                        if committed > limit
                        else "WARNING"
                        if ratio >= row.warn_ratio
                        else "OK"
                    ),
                    "unpriced_agent_runs": used["unpriced_agent_runs"],
                }
            )
        today = spend(datetime.fromisoformat(_period_start("DAILY", at, timezone)), at)
        return {"budgets": periods_now, "today": today, "timezone": timezone}

    return {
        "schema_version": 1,
        "timezone": timezone,
        "readings": [
            {"at": at, "treasury": treasury(moment), "budget": budget(moment)}
            for at, moment in zip(ats, instants, strict=True)
        ],
        "note": NOTE,
    }
