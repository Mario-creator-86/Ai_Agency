"""Phase 11 — turning real financial evidence into virtual books, and nothing else.

What this module guarantees, and how:

  **One verified dollar becomes exactly one VR$, once.** Evidence carries a unique
  ``(source, external_reference)``; minting refuses anything that is not SETTLED and stamps the
  row with the transaction it produced. A second attempt finds the stamp and refuses.

  **Forecasts cannot be spent.** ESTIMATED and PENDING_PAYOUT evidence never reaches the ledger,
  so it never reaches a cash balance. The treasury view reports those figures beside the
  spendable one, labelled, rather than hiding them or adding them in.

  **The books always balance.** Every posting goes through :func:`post_transaction`, which
  refuses an unbalanced set of lines before it writes anything. :func:`trial_balance` re-checks
  the whole ledger from the stored rows.

  **Nothing is deleted.** A correction is a reversing transaction that points at the original.

What this module deliberately does not do: move real money, contact any payment provider, decide
that revenue exists, or let an agent mint. Minting is a controlled ledger event driven by Owner
action, exactly as `../architecture/66_VIRTUAL_REAL_ECONOMY_ENGINE.md` requires. Spending VR$
(procurement, financing) is Phase 13/14 and has no code here yet, which is why the treasury view
reports a deficit as a fact and does not pretend to enforce a spending freeze that nothing could
trip.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.economy.models import (
    MICROS,
    FXSnapshot,
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
    OwnerFundingEvent,
    ProviderCostRecord,
    RevenueEvidence,
)
from app.services import append_event, utc_now


class EconomyError(Exception):
    """A refusal the caller can act on: wrong state, missing rate, duplicate reference."""


#: The chart of accounts required by `66_VIRTUAL_REAL_ECONOMY_ENGINE.md` §"Accounting method".
#: (code, name, type, normal balance, money class, description)
CHART_OF_ACCOUNTS: tuple[tuple[str, str, str, str, str | None, str], ...] = (
    ("1000", "VR Cash", "ASSET", "DEBIT", "VR_CASH", "Spendable in-world treasury."),
    (
        "1010",
        "Restricted Cash",
        "ASSET",
        "DEBIT",
        "VR_RESTRICTED",
        "Reserved against obligations and contingencies; not available to spend.",
    ),
    (
        "1100",
        "Receivables",
        "ASSET",
        "DEBIT",
        "VR_RECEIVABLE",
        "Earned but not settled. Tracked, never spendable on its own.",
    ),
    ("1500", "Fixed Assets", "ASSET", "DEBIT", None, "Capitalised virtual property and equipment."),
    (
        "1590",
        "Accumulated Depreciation",
        "ASSET",
        "CREDIT",
        None,
        "Contra-asset. Depreciation booked against fixed assets.",
    ),
    ("2000", "Debt Principal", "LIABILITY", "CREDIT", "VR_DEBT", "Virtual borrowings outstanding."),
    (
        "2100",
        "Accrued Interest",
        "LIABILITY",
        "CREDIT",
        "VR_DEBT",
        "Interest accrued on virtual debt and not yet paid.",
    ),
    ("3000", "Owner Capital", "EQUITY", "CREDIT", None, "Owner contributions. Never repaid."),
    ("3900", "Retained Earnings", "EQUITY", "CREDIT", None, "Accumulated virtual result."),
    ("4000", "Revenue — YouTube", "REVENUE", "CREDIT", None, "Settled platform payouts."),
    ("4010", "Revenue — Donations", "REVENUE", "CREDIT", None, "Settled viewer contributions."),
    ("4020", "Revenue — Sponsorship", "REVENUE", "CREDIT", None, "Settled sponsor payments."),
    ("4090", "Revenue — Other", "REVENUE", "CREDIT", None, "Any other settled inflow."),
    (
        "5000",
        "Provider & Cloud Expense",
        "EXPENSE",
        "DEBIT",
        None,
        "Real external model, render and hosting costs mirrored into VR$.",
    ),
    ("5100", "Marketing Expense", "EXPENSE", "DEBIT", None, "Promotion and distribution spend."),
    (
        "5200",
        "Virtual Procurement Expense",
        "EXPENSE",
        "DEBIT",
        None,
        "Market-priced in-world purchases that are expensed rather than capitalised.",
    ),
    ("5300", "Depreciation Expense", "EXPENSE", "DEBIT", None, "Periodic write-down of assets."),
    ("5400", "Interest Expense", "EXPENSE", "DEBIT", None, "Cost of virtual borrowing."),
)

#: Which revenue account each evidence source credits.
REVENUE_ACCOUNT_BY_SOURCE = {
    "YOUTUBE": "4000",
    "DONATION": "4010",
    "SPONSORSHIP": "4020",
    "OTHER": "4090",
}

VALID_SOURCES = frozenset(REVENUE_ACCOUNT_BY_SOURCE)
#: Only these are recordable. SETTLED is reached through :func:`settle_evidence`, and REVERSED
#: through :func:`reverse_transaction`, so neither can be asserted directly by a caller.
RECORDABLE_STATUSES = frozenset({"ESTIMATED", "PENDING_PAYOUT", "SETTLED"})
#: The one status that may become VR$.
MINTABLE_STATUS = "SETTLED"


# ---------------------------------------------------------------------------- money helpers --


def to_micros(amount: float | int | str) -> int:
    """Convert a decimal amount of currency to integer micros, rounding half away from zero.

    Accepts a string so an exact decimal from an invoice survives without ever becoming a float.
    """
    text = str(amount).strip()
    negative = text.startswith("-")
    if negative:
        text = text[1:]
    whole, _, frac = text.partition(".")
    whole = whole or "0"
    if not whole.isdigit() or (frac and not frac.isdigit()):
        raise EconomyError(f"{amount!r} is not a decimal amount.")
    # Seven digits: six that become micros, and a seventh that decides the rounding. Pad to
    # seven so a whole amount like "5" still has a rounding digit to read.
    frac = (frac + "0000000")[:7]
    micros = int(whole) * MICROS + int(frac[:6])
    if int(frac[6]) >= 5:
        micros += 1
    return -micros if negative else micros


def format_micros(micros: int) -> str:
    """Render micros as a plain decimal string, for display and for events."""
    sign = "-" if micros < 0 else ""
    micros = abs(micros)
    return f"{sign}{micros // MICROS}.{micros % MICROS:06d}".rstrip("0").rstrip(".") or "0"


def _convert_to_usd(
    session: Session, amount_micros: int, currency: str, fx_snapshot_id: str | None
) -> tuple[int, str | None]:
    """Return the USD value of an amount and the snapshot that justified it.

    Refuses to guess. A non-USD amount without a recorded rate is rejected rather than converted
    at an invented one, which is the whole point of `66_VIRTUAL_REAL_ECONOMY_ENGINE.md`
    §"Multi-currency".
    """
    currency = currency.upper()
    if currency == "USD":
        if fx_snapshot_id is not None:
            raise EconomyError("USD evidence needs no exchange rate; leave fx_snapshot_id empty.")
        return amount_micros, None
    if not fx_snapshot_id:
        raise EconomyError(
            f"{currency} needs a recorded exchange rate. Record an FX snapshot first; "
            "the studio does not invent rates."
        )
    snapshot = session.get(FXSnapshot, fx_snapshot_id)
    if snapshot is None:
        raise EconomyError("That FX snapshot does not exist.")
    if snapshot.base_currency != currency or snapshot.quote_currency != "USD":
        raise EconomyError(
            f"FX snapshot converts {snapshot.base_currency}->{snapshot.quote_currency}, "
            f"but the amount is in {currency} and must reach USD."
        )
    # Round half up on the final micro, so a conversion never silently loses a fraction.
    usd = (amount_micros * snapshot.rate_micros + MICROS // 2) // MICROS
    return usd, snapshot.id


# --------------------------------------------------------------------------------- seeding --


def seed_chart_of_accounts(engine: Engine) -> int:
    """Create any missing accounts. Idempotent; never edits an account that already exists."""
    created = 0
    with Session(engine) as session, session.begin():
        existing = set(session.scalars(select(LedgerAccount.code)).all())
        for code, name, kind, normal, money_class, description in CHART_OF_ACCOUNTS:
            if code in existing:
                continue
            session.add(
                LedgerAccount(
                    code=code,
                    name=name,
                    account_type=kind,
                    normal_balance=normal,
                    money_class=money_class,
                    description=description,
                )
            )
            created += 1
    return created


# --------------------------------------------------------------------------------- posting --


def post_transaction(
    session: Session,
    *,
    kind: str,
    memo: str,
    lines: list[tuple[str, int, int]],
    correlation_id: str,
    reverses_transaction_id: str | None = None,
) -> LedgerTransaction:
    """Write one balanced transaction, or refuse and write nothing.

    ``lines`` are ``(account_code, debit_micros, credit_micros)``. The balance check happens
    before any row is added: an unbalanced posting must not exist even briefly, because the
    surrounding transaction could be committed by a later caller.
    """
    if not lines:
        raise EconomyError("A transaction needs at least two lines.")
    debits = sum(line[1] for line in lines)
    credits = sum(line[2] for line in lines)
    if debits != credits:
        raise EconomyError(
            f"Refusing to post: debits {format_micros(debits)} "
            f"do not equal credits {format_micros(credits)}."
        )
    if debits == 0:
        raise EconomyError("Refusing to post a transaction with no value.")
    for code, debit, credit in lines:
        if (debit == 0) == (credit == 0):
            raise EconomyError(f"Line for account {code} must be either a debit or a credit.")
        if debit < 0 or credit < 0:
            raise EconomyError("A ledger line cannot be negative; post the other side instead.")
        if session.get(LedgerAccount, code) is None:
            raise EconomyError(f"Account {code} is not in the chart of accounts.")

    transaction = LedgerTransaction(
        id=str(uuid4()),
        kind=kind,
        memo=memo,
        posted_at=utc_now(),
        reverses_transaction_id=reverses_transaction_id,
    )
    session.add(transaction)
    session.flush()
    for code, debit, credit in lines:
        session.add(
            LedgerEntry(
                id=str(uuid4()),
                transaction_id=transaction.id,
                account_code=code,
                debit_micros=debit,
                credit_micros=credit,
            )
        )
    event = append_event(
        session,
        "economy.transaction_posted",
        "ledger",
        transaction.id,
        1,
        {
            "kind": kind,
            "memo": memo,
            "amount_vr": format_micros(debits),
            "reverses": reverses_transaction_id,
            "lines": [
                {"account": code, "debit": format_micros(d), "credit": format_micros(c)}
                for code, d, c in lines
            ],
        },
        correlation_id,
    )
    transaction.event_id = event.event_id
    return transaction


# -------------------------------------------------------------------------------- evidence --


def record_fx_snapshot(
    engine: Engine,
    *,
    base_currency: str,
    quote_currency: str,
    rate: str,
    source: str,
    observed_at: str,
) -> dict:
    """Store an observed rate so a conversion can cite it later."""
    rate_micros = to_micros(rate)
    if rate_micros <= 0:
        raise EconomyError("An exchange rate must be positive.")
    with Session(engine) as session, session.begin():
        snapshot = FXSnapshot(
            id=str(uuid4()),
            base_currency=base_currency.upper(),
            quote_currency=quote_currency.upper(),
            rate_micros=rate_micros,
            source=source,
            observed_at=observed_at,
            recorded_at=utc_now(),
        )
        session.add(snapshot)
        session.flush()
        return _fx_view(snapshot)


def record_revenue_evidence(
    engine: Engine,
    *,
    source: str,
    external_reference: str,
    status: str,
    amount: str,
    currency: str,
    fx_snapshot_id: str | None = None,
    detail: dict | None = None,
    correlation_id: str | None = None,
) -> dict:
    """Record that something happened outside the application. Mints nothing.

    A duplicate ``(source, external_reference)`` is refused rather than stored, because a second
    copy of one payout is exactly how a ledger ends up with money that never existed.
    """
    source = source.upper()
    status = status.upper()
    if source not in VALID_SOURCES:
        raise EconomyError(
            f"Unknown source {source}. Use one of: {', '.join(sorted(VALID_SOURCES))}."
        )
    if status not in RECORDABLE_STATUSES:
        raise EconomyError(
            f"Record evidence as {', '.join(sorted(RECORDABLE_STATUSES))}. "
            "REVERSED is reached by reversing its transaction."
        )
    if not external_reference.strip():
        raise EconomyError("Evidence needs the source's own reference; it is the idempotency key.")
    amount_micros = to_micros(amount)
    if amount_micros <= 0:
        raise EconomyError("Evidence must carry a positive amount.")

    correlation = correlation_id or str(uuid4())
    with Session(engine) as session, session.begin():
        duplicate = session.scalar(
            select(RevenueEvidence).where(
                RevenueEvidence.source == source,
                RevenueEvidence.external_reference == external_reference,
            )
        )
        if duplicate is not None:
            raise EconomyError(
                f"{source} reference {external_reference} is already recorded "
                f"(status {duplicate.status}). One payout is recorded once."
            )
        usd_micros, used_fx = _convert_to_usd(session, amount_micros, currency, fx_snapshot_id)
        now = utc_now()
        evidence = RevenueEvidence(
            id=str(uuid4()),
            source=source,
            external_reference=external_reference.strip(),
            status=status,
            original_amount_micros=amount_micros,
            original_currency=currency.upper(),
            usd_micros=usd_micros,
            fx_snapshot_id=used_fx,
            detail_json=detail or {},
            recorded_at=now,
            settled_at=now if status == MINTABLE_STATUS else None,
        )
        session.add(evidence)
        event = append_event(
            session,
            "economy.evidence_recorded",
            "revenue_evidence",
            evidence.id,
            1,
            {
                "source": source,
                "reference": evidence.external_reference,
                "status": status,
                "amount": format_micros(amount_micros),
                "currency": evidence.original_currency,
                "usd": format_micros(usd_micros),
                "spendable": False,
            },
            correlation,
        )
        evidence.event_id = event.event_id
        session.flush()
        return _evidence_view(evidence)


def settle_evidence(engine: Engine, evidence_id: str, *, correlation_id: str | None = None) -> dict:
    """Mark evidence as settled. Still mints nothing; minting stays a separate decision."""
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session, session.begin():
        evidence = session.get(RevenueEvidence, evidence_id)
        if evidence is None:
            raise EconomyError("No such evidence.")
        if evidence.status == "REVERSED":
            raise EconomyError("Reversed evidence cannot be settled again.")
        if evidence.status == MINTABLE_STATUS:
            return _evidence_view(evidence)
        previous = evidence.status
        evidence.status = MINTABLE_STATUS
        evidence.settled_at = utc_now()
        append_event(
            session,
            "economy.evidence_settled",
            "revenue_evidence",
            evidence.id,
            2,
            {
                "previous_status": previous,
                "usd": format_micros(evidence.usd_micros),
                "minted": False,
            },
            correlation,
        )
        session.flush()
        return _evidence_view(evidence)


def mint_from_evidence(
    engine: Engine, evidence_id: str, *, correlation_id: str | None = None
) -> dict:
    """Turn settled evidence into VR$, once.

    The 1:1 rule lives here: the transaction debits VR Cash and credits the revenue account for
    the source, both by the evidence's USD value. Nothing scales it, and nothing rounds it a
    second time — the conversion already happened when the evidence was recorded.
    """
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session, session.begin():
        evidence = session.get(RevenueEvidence, evidence_id)
        if evidence is None:
            raise EconomyError("No such evidence.")
        if evidence.minted_transaction_id is not None:
            raise EconomyError(
                "This evidence has already been minted. One verified dollar becomes one VR$ once."
            )
        if evidence.status != MINTABLE_STATUS:
            raise EconomyError(
                f"Evidence is {evidence.status}. Only settled evidence can be minted — "
                "forecast and pending payouts are never spendable."
            )
        account = REVENUE_ACCOUNT_BY_SOURCE[evidence.source]
        transaction = post_transaction(
            session,
            kind="MINT",
            memo=f"{evidence.source} {evidence.external_reference}",
            lines=[("1000", evidence.usd_micros, 0), (account, 0, evidence.usd_micros)],
            correlation_id=correlation,
        )
        evidence.minted_transaction_id = transaction.id
        append_event(
            session,
            "economy.vr_minted",
            "revenue_evidence",
            evidence.id,
            3,
            {
                "transaction_id": transaction.id,
                "vr_minted": format_micros(evidence.usd_micros),
                "source": evidence.source,
                "reference": evidence.external_reference,
            },
            correlation,
        )
        session.flush()
        return {"evidence": _evidence_view(evidence), "transaction_id": transaction.id}


def reverse_transaction(
    engine: Engine, transaction_id: str, *, reason: str, correlation_id: str | None = None
) -> dict:
    """Undo a posting by posting its mirror. The original is never touched.

    A chargeback can push VR Cash negative. That is allowed and reported: pretending the money is
    still there would be worse than showing a deficit, and `66_VIRTUAL_REAL_ECONOMY_ENGINE.md`
    §"Reversals" expects treasury stress rather than a refusal to record reality.
    """
    if not reason.strip():
        raise EconomyError("A reversal needs a reason; it stays in the books beside the posting.")
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session, session.begin():
        original = session.get(LedgerTransaction, transaction_id)
        if original is None:
            raise EconomyError("No such transaction.")
        if original.reverses_transaction_id is not None:
            raise EconomyError("A reversal cannot itself be reversed; post a new correction.")
        already = session.scalar(
            select(LedgerTransaction).where(
                LedgerTransaction.reverses_transaction_id == transaction_id
            )
        )
        if already is not None:
            raise EconomyError("That transaction has already been reversed.")

        entries = session.scalars(
            select(LedgerEntry).where(LedgerEntry.transaction_id == transaction_id)
        ).all()
        mirrored = [(e.account_code, e.credit_micros, e.debit_micros) for e in entries]
        reversal = post_transaction(
            session,
            kind="REVERSAL",
            memo=f"Reversal of {original.kind}: {reason.strip()}",
            lines=mirrored,
            correlation_id=correlation,
            reverses_transaction_id=transaction_id,
        )
        # Evidence that produced the original posting is now reversed, not merely un-minted:
        # the outside world took the money back.
        evidence = session.scalar(
            select(RevenueEvidence).where(RevenueEvidence.minted_transaction_id == transaction_id)
        )
        if evidence is not None:
            evidence.status = "REVERSED"
            append_event(
                session,
                "economy.evidence_reversed",
                "revenue_evidence",
                evidence.id,
                4,
                {"reversal_transaction_id": reversal.id, "reason": reason.strip()},
                correlation,
            )
        session.flush()
        return {"reversal_transaction_id": reversal.id, "reversed": transaction_id}


def record_owner_funding(
    engine: Engine,
    *,
    funding_type: str,
    amount: str,
    currency: str,
    fx_snapshot_id: str | None = None,
    annual_rate_bps: int | None = None,
    maturity_date: str | None = None,
    note: str = "",
    correlation_id: str | None = None,
) -> dict:
    """Record Owner money going in, and post it according to what kind of money it is.

    A contribution credits equity; a loan credits a liability and carries its terms. The two are
    not interchangeable, and the ledger is where the difference has to show.
    """
    funding_type = funding_type.upper()
    if funding_type not in {"CAPITAL_CONTRIBUTION", "OWNER_LOAN"}:
        raise EconomyError("Funding is either CAPITAL_CONTRIBUTION or OWNER_LOAN.")
    if funding_type == "OWNER_LOAN" and (annual_rate_bps is None or not maturity_date):
        raise EconomyError(
            "An Owner loan needs a rate and a maturity date; otherwise record it as capital."
        )
    if funding_type == "CAPITAL_CONTRIBUTION" and (annual_rate_bps or maturity_date):
        raise EconomyError("A capital contribution carries no rate or maturity; it is not repaid.")
    amount_micros = to_micros(amount)
    if amount_micros <= 0:
        raise EconomyError("Funding must be a positive amount.")

    correlation = correlation_id or str(uuid4())
    with Session(engine) as session, session.begin():
        usd_micros, used_fx = _convert_to_usd(session, amount_micros, currency, fx_snapshot_id)
        credit_account = "3000" if funding_type == "CAPITAL_CONTRIBUTION" else "2000"
        transaction = post_transaction(
            session,
            kind="OWNER_CAPITAL" if funding_type == "CAPITAL_CONTRIBUTION" else "OWNER_LOAN",
            memo=note.strip() or funding_type.replace("_", " ").title(),
            lines=[("1000", usd_micros, 0), (credit_account, 0, usd_micros)],
            correlation_id=correlation,
        )
        funding = OwnerFundingEvent(
            id=str(uuid4()),
            funding_type=funding_type,
            amount_micros=amount_micros,
            currency=currency.upper(),
            usd_micros=usd_micros,
            fx_snapshot_id=used_fx,
            annual_rate_bps=annual_rate_bps,
            maturity_date=maturity_date,
            note=note.strip(),
            transaction_id=transaction.id,
            recorded_at=utc_now(),
        )
        session.add(funding)
        event = append_event(
            session,
            "economy.owner_funding_recorded",
            "owner_funding",
            funding.id,
            1,
            {
                "funding_type": funding_type,
                "vr": format_micros(usd_micros),
                "credited_account": credit_account,
                "annual_rate_bps": annual_rate_bps,
                "maturity_date": maturity_date,
                "moves_real_money": False,
            },
            correlation,
        )
        funding.event_id = event.event_id
        session.flush()
        return _funding_view(funding)


# ------------------------------------------------------------------------ provider costs --


def record_provider_cost(
    engine: Engine,
    *,
    provider: str,
    external_reference: str,
    status: str,
    amount: str,
    currency: str = "USD",
    fx_snapshot_id: str | None = None,
    attribution: dict | None = None,
    correlation_id: str | None = None,
) -> dict:
    """Record what the studio actually spends with an external provider.

    The mirror image of revenue, and deliberately symmetric with it: an ESTIMATED cost is tracked
    and shown but never posted, because an estimate is not a bill; a BILLED cost posts at once,
    debiting Provider & Cloud Expense and crediting VR Cash. That posting is the only way VR Cash
    can currently fall, and it is what makes a treasury deficit reachable — a studio that shows
    income and no cost of running itself is telling a flattering story rather than a true one.
    """
    provider = provider.strip()
    status = status.upper()
    if not provider:
        raise EconomyError("Name the provider that billed.")
    if status not in {"ESTIMATED", "BILLED"}:
        raise EconomyError("A provider cost is either ESTIMATED or BILLED.")
    if not external_reference.strip():
        raise EconomyError("A provider cost needs the provider's own reference.")
    amount_micros = to_micros(amount)
    if amount_micros <= 0:
        raise EconomyError("A provider cost must be a positive amount.")

    correlation = correlation_id or str(uuid4())
    with Session(engine) as session, session.begin():
        duplicate = session.scalar(
            select(ProviderCostRecord).where(
                ProviderCostRecord.provider == provider,
                ProviderCostRecord.external_reference == external_reference.strip(),
            )
        )
        if duplicate is not None:
            raise EconomyError(
                f"{provider} reference {external_reference} is already recorded "
                f"(status {duplicate.status}). One invoice is charged once."
            )
        usd_micros, used_fx = _convert_to_usd(session, amount_micros, currency, fx_snapshot_id)
        now = utc_now()
        cost = ProviderCostRecord(
            id=str(uuid4()),
            provider=provider,
            external_reference=external_reference.strip(),
            status=status,
            amount_micros=amount_micros,
            currency=currency.upper(),
            usd_micros=usd_micros,
            fx_snapshot_id=used_fx,
            attribution_json=attribution or {},
            recorded_at=now,
            billed_at=now if status == "BILLED" else None,
        )
        session.add(cost)
        if status == "BILLED":
            transaction = post_transaction(
                session,
                kind="PROVIDER_COST",
                memo=f"{provider} {cost.external_reference}",
                lines=[("5000", usd_micros, 0), ("1000", 0, usd_micros)],
                correlation_id=correlation,
            )
            cost.transaction_id = transaction.id
        event = append_event(
            session,
            "economy.provider_cost_recorded",
            "provider_cost",
            cost.id,
            1,
            {
                "provider": provider,
                "reference": cost.external_reference,
                "status": status,
                "vr": format_micros(usd_micros),
                "posted": status == "BILLED",
            },
            correlation,
        )
        cost.event_id = event.event_id
        session.flush()
        return _cost_view(cost)


def bill_provider_cost(engine: Engine, cost_id: str, *, correlation_id: str | None = None) -> dict:
    """Confirm an estimate became a real bill, and post it once."""
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session, session.begin():
        cost = session.get(ProviderCostRecord, cost_id)
        if cost is None:
            raise EconomyError("No such provider cost.")
        if cost.transaction_id is not None:
            raise EconomyError("That invoice has already been posted.")
        cost.status = "BILLED"
        cost.billed_at = utc_now()
        transaction = post_transaction(
            session,
            kind="PROVIDER_COST",
            memo=f"{cost.provider} {cost.external_reference}",
            lines=[("5000", cost.usd_micros, 0), ("1000", 0, cost.usd_micros)],
            correlation_id=correlation,
        )
        cost.transaction_id = transaction.id
        append_event(
            session,
            "economy.provider_cost_billed",
            "provider_cost",
            cost.id,
            2,
            {"transaction_id": transaction.id, "vr": format_micros(cost.usd_micros)},
            correlation,
        )
        session.flush()
        return _cost_view(cost)


def list_provider_costs(
    engine: Engine, *, status: str | None = None, limit: int = 100
) -> list[dict]:
    with Session(engine) as session:
        query = (
            select(ProviderCostRecord).order_by(ProviderCostRecord.recorded_at.desc()).limit(limit)
        )
        if status:
            query = query.where(ProviderCostRecord.status == status.upper())
        return [_cost_view(c) for c in session.scalars(query).all()]


# ----------------------------------------------------------------------------- projections --


def _account_balances(session: Session) -> dict[str, int]:
    """Signed balance per account, in each account's own normal direction."""
    rows = session.execute(
        select(
            LedgerEntry.account_code,
            func.sum(LedgerEntry.debit_micros),
            func.sum(LedgerEntry.credit_micros),
        ).group_by(LedgerEntry.account_code)
    ).all()
    accounts = {a.code: a for a in session.scalars(select(LedgerAccount)).all()}
    balances: dict[str, int] = {}
    for code, debit, credit in rows:
        account = accounts.get(code)
        if account is None:
            continue
        debit, credit = int(debit or 0), int(credit or 0)
        balances[code] = debit - credit if account.normal_balance == "DEBIT" else credit - debit
    return balances


def trial_balance(engine: Engine) -> dict:
    """Re-add every stored line. Returns the totals and whether the books balance."""
    with Session(engine) as session:
        debit, credit = session.execute(
            select(func.sum(LedgerEntry.debit_micros), func.sum(LedgerEntry.credit_micros))
        ).one()
        debit, credit = int(debit or 0), int(credit or 0)
        return {
            "total_debits": format_micros(debit),
            "total_credits": format_micros(credit),
            "balanced": debit == credit,
            "difference": format_micros(debit - credit),
        }


def treasury_snapshot(engine: Engine) -> dict:
    """What the studio has, what it is owed, what it owes, and what it merely expects.

    Every figure is labelled with the money class it belongs to, because
    `66_VIRTUAL_REAL_ECONOMY_ENGINE.md` §"Public representation" requires the interface to say
    whether a number is VERIFIED, PENDING, FORECAST or VR VIRTUAL — and the only way to keep that
    honest is to carry the label with the number instead of leaving it to the page.
    """
    with Session(engine) as session:
        accounts = {a.code: a for a in session.scalars(select(LedgerAccount)).all()}
        balances = _account_balances(session)

        by_class: dict[str, int] = {}
        for code, balance in balances.items():
            money_class = accounts[code].money_class
            if money_class:
                by_class[money_class] = by_class.get(money_class, 0) + balance

        # Evidence that has not settled is reported, never added to spendable cash.
        pending_rows = session.execute(
            select(RevenueEvidence.status, func.sum(RevenueEvidence.usd_micros))
            .where(RevenueEvidence.status.in_(("ESTIMATED", "PENDING_PAYOUT")))
            .group_by(RevenueEvidence.status)
        ).all()
        unsettled = {status: int(total or 0) for status, total in pending_rows}

        # Estimates that have not become invoices: an obligation the studio can see coming,
        # reported without it touching the books.
        unbilled = int(
            session.scalar(
                select(func.sum(ProviderCostRecord.usd_micros)).where(
                    ProviderCostRecord.status == "ESTIMATED"
                )
            )
            or 0
        )

        spendable = by_class.get("VR_CASH", 0)
        return {
            "unit": "VR$",
            "anchor": "1 verified USD = 1 VR$",
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
                for money_class in ("VR_CASH", "VR_RESTRICTED", "VR_RECEIVABLE", "VR_DEBT")
            ],
            "not_spendable": [
                {
                    "money_class": "PENDING_EXTERNAL",
                    "label": "PENDING",
                    "amount": format_micros(unsettled.get("PENDING_PAYOUT", 0)),
                    "spendable": False,
                },
                {
                    "money_class": "FORECAST",
                    "label": "FORECAST",
                    "amount": format_micros(unsettled.get("ESTIMATED", 0)),
                    "spendable": False,
                },
            ],
            "accounts": [
                {
                    "code": code,
                    "name": accounts[code].name,
                    "type": accounts[code].account_type,
                    "money_class": accounts[code].money_class,
                    "balance": format_micros(balances.get(code, 0)),
                }
                for code in sorted(accounts)
                if balances.get(code, 0) != 0
            ],
            "unbilled_provider_costs": {
                "label": "ESTIMAT",
                "amount": format_micros(unbilled),
                "posted": False,
            },
            "in_deficit": spendable < 0,
            "trial_balance": trial_balance(engine),
            # Said plainly so no reader mistakes these books for filed accounts.
            "disclaimer": (
                "Registru virtual de management. Nu sunt conturi contabile depuse legal și "
                "nicio sumă de aici nu mișcă bani reali."
            ),
        }


def list_evidence(engine: Engine, *, status: str | None = None, limit: int = 100) -> list[dict]:
    with Session(engine) as session:
        query = select(RevenueEvidence).order_by(RevenueEvidence.recorded_at.desc()).limit(limit)
        if status:
            query = query.where(RevenueEvidence.status == status.upper())
        return [_evidence_view(e) for e in session.scalars(query).all()]


def list_transactions(engine: Engine, *, limit: int = 50) -> list[dict]:
    with Session(engine) as session:
        transactions = session.scalars(
            select(LedgerTransaction).order_by(LedgerTransaction.posted_at.desc()).limit(limit)
        ).all()
        ids = [t.id for t in transactions]
        entries: dict[str, list[LedgerEntry]] = {}
        if ids:
            for entry in session.scalars(
                select(LedgerEntry).where(LedgerEntry.transaction_id.in_(ids))
            ).all():
                entries.setdefault(entry.transaction_id, []).append(entry)
        return [
            {
                "id": t.id,
                "kind": t.kind,
                "memo": t.memo,
                "posted_at": t.posted_at,
                "reverses_transaction_id": t.reverses_transaction_id,
                "amount": format_micros(sum(e.debit_micros for e in entries.get(t.id, []))),
                "lines": [
                    {
                        "account": e.account_code,
                        "debit": format_micros(e.debit_micros),
                        "credit": format_micros(e.credit_micros),
                    }
                    for e in entries.get(t.id, [])
                ],
            }
            for t in transactions
        ]


def list_accounts(engine: Engine) -> list[dict]:
    with Session(engine) as session:
        return [
            {
                "code": a.code,
                "name": a.name,
                "type": a.account_type,
                "normal_balance": a.normal_balance,
                "money_class": a.money_class,
                "description": a.description,
            }
            for a in session.scalars(select(LedgerAccount).order_by(LedgerAccount.code)).all()
        ]


def list_owner_funding(engine: Engine) -> list[dict]:
    with Session(engine) as session:
        return [
            _funding_view(f)
            for f in session.scalars(
                select(OwnerFundingEvent).order_by(OwnerFundingEvent.recorded_at.desc())
            ).all()
        ]


# ------------------------------------------------------------------------------------ views --


def _evidence_view(evidence: RevenueEvidence) -> dict:
    return {
        "id": evidence.id,
        "source": evidence.source,
        "external_reference": evidence.external_reference,
        "status": evidence.status,
        "label": "VERIFIED"
        if evidence.status == MINTABLE_STATUS
        else (
            "PENDING"
            if evidence.status == "PENDING_PAYOUT"
            else "FORECAST"
            if evidence.status == "ESTIMATED"
            else "REVERSED"
        ),
        "original_amount": format_micros(evidence.original_amount_micros),
        "original_currency": evidence.original_currency,
        "usd": format_micros(evidence.usd_micros),
        "fx_snapshot_id": evidence.fx_snapshot_id,
        "minted": evidence.minted_transaction_id is not None,
        "minted_transaction_id": evidence.minted_transaction_id,
        "spendable": False,
        "recorded_at": evidence.recorded_at,
        "settled_at": evidence.settled_at,
        "detail": evidence.detail_json,
    }


def _cost_view(cost: ProviderCostRecord) -> dict:
    return {
        "id": cost.id,
        "provider": cost.provider,
        "external_reference": cost.external_reference,
        "status": cost.status,
        "label": "BILLED" if cost.status == "BILLED" else "ESTIMAT",
        "original_amount": format_micros(cost.amount_micros),
        "currency": cost.currency,
        "vr": format_micros(cost.usd_micros),
        "posted": cost.transaction_id is not None,
        "transaction_id": cost.transaction_id,
        "attribution": cost.attribution_json,
        "recorded_at": cost.recorded_at,
        "billed_at": cost.billed_at,
    }


def _funding_view(funding: OwnerFundingEvent) -> dict:
    return {
        "id": funding.id,
        "funding_type": funding.funding_type,
        "amount": format_micros(funding.amount_micros),
        "currency": funding.currency,
        "vr": format_micros(funding.usd_micros),
        "annual_rate_bps": funding.annual_rate_bps,
        "maturity_date": funding.maturity_date,
        "note": funding.note,
        "transaction_id": funding.transaction_id,
        "recorded_at": funding.recorded_at,
        "moves_real_money": False,
    }


def _fx_view(snapshot: FXSnapshot) -> dict:
    return {
        "id": snapshot.id,
        "base_currency": snapshot.base_currency,
        "quote_currency": snapshot.quote_currency,
        "rate": format_micros(snapshot.rate_micros),
        "source": snapshot.source,
        "observed_at": snapshot.observed_at,
        "recorded_at": snapshot.recorded_at,
    }
