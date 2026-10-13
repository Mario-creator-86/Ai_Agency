"""What the vendor actually billed replaces what the studio estimated, exactly once.

Measured before this file: every `provider_cost_record` row the studio writes itself is
ESTIMATED at catalogue or Owner prices, `bill_provider_cost` posts *another* row's worth of
money without touching the estimate it confirms, and `spend_since` (backend/app/economy/
budget.py) sums every row in the period whatever its status — so a render estimated at 4.20
and later billed at 4.55 was counted at 8.75 by the day's budget. Nothing reconciled them
and nothing said so.

Reconciliation is the Owner's act, because only he sees the invoice. What is asserted here:
the invoice replaces the estimates it covers and the period then counts the billed figure
once; the same command id twice is one invoice; a stale `expected_version` is refused; what
the invoice could not match is reported by name and never silently dropped or silently kept;
and a corrected invoice reverses the first one in the ledger instead of editing it.

Nothing here reaches a vendor: the invoice is a number the Owner types.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.economy.budget import BudgetCommand, budget_status, set_budget, spend_since
from app.economy.models import ProviderCostRecord, ProviderReconciliation
from app.economy.services import (
    EconomyError,
    ReconciliationCommand,
    list_reconciliations,
    reconcile_provider_invoice,
    record_provider_cost,
    seed_chart_of_accounts,
    treasury_snapshot,
    trial_balance,
)
from app.models import DomainEvent
from sqlalchemy import select
from sqlalchemy.orm import Session

DAY = "2026-09-18"
START = f"{DAY}T00:00:00+00:00"
END = "2026-09-19T00:00:00+00:00"


@pytest.fixture
def books(engine):
    seed_chart_of_accounts(engine)
    return engine


def estimate(engine, reference, amount, *, provider="runway", at=None, attribution=None, **kw):
    """One ESTIMATED row, stamped when the spend happened rather than when the test ran."""
    view = record_provider_cost(
        engine,
        provider=provider,
        external_reference=reference,
        status="ESTIMATED",
        amount=amount,
        attribution=attribution or {},
        **kw,
    )
    if at is not None:
        with Session(engine) as session, session.begin():
            session.get(ProviderCostRecord, view["id"]).recorded_at = at
    return view


def invoice(engine, **kw) -> dict:
    fields: dict = {
        "command_id": uuid4(),
        "provider": "runway",
        "external_reference": f"INV-{uuid4().hex[:8]}",
        "amount": "10",
        "scope": "PERIOD",
        "period_start": START,
        "period_end": END,
    }
    fields.update(kw)
    return reconcile_provider_invoice(engine, ReconciliationCommand(**fields))


# ------------------------------------------------- the estimates it covers stop counting


def test_an_invoice_replaces_the_estimates_it_covers_and_the_period_counts_it_once(books):
    estimate(books, "render:a:scene:1:motion", "4.20", at=f"{DAY}T09:00:00+00:00")
    estimate(books, "render:a:scene:2:motion", "3.00", at=f"{DAY}T09:30:00+00:00")
    with Session(books) as session:
        before = spend_since(session, START)
    assert before["spent_usd"] == "7.2", "both estimates counted before anyone reconciled"

    answer = invoice(books, external_reference="RW-2026-09", amount="8.05")
    assert answer["matched"] == 2 and answer["matched_vr"] == "7.2"
    assert answer["billed_vr"] == "8.05" and answer["difference_vr"] == "0.85"
    assert answer["unmatched"] == []
    # The bill is stamped at the moment of the last spend it pays for, so the period that
    # counted the estimates counts the bill.
    assert answer["counted_at"] == f"{DAY}T09:30:00+00:00"

    with Session(books) as session:
        after = spend_since(session, START)
    assert after["spent_usd"] == "8.05", "the billed figure, exactly once"
    provider = after["by_provider"][0]
    assert provider["estimated_usd_micros"] == 0 and provider["billed_usd_micros"] == 8_050_000

    with Session(books) as session:
        rows = session.scalars(select(ProviderCostRecord)).all()
        estimates = [r for r in rows if r.status == "ESTIMATED"]
        assert len(rows) == 3 and len(estimates) == 2
        assert all(r.reconciled_at and r.reconciled_by_id == answer["id"] for r in estimates)
        billed = next(r for r in rows if r.status == "BILLED")
        assert billed.id == answer["cost_id"] and billed.reconciled_at is None
        assert billed.transaction_id is not None, "a bill posts; an estimate never did"
    # The books still balance and the money left VR Cash once.
    assert trial_balance(books)["balanced"] is True
    assert treasury_snapshot(books)["spendable"]["amount"] == "-8.05"


def test_a_budget_that_refused_on_estimates_reads_the_invoice_afterwards(books):
    set_budget(books, BudgetCommand(period="DAILY", limit_usd="10"))
    estimate(books, "render:b:scene:1:motion", "9.00", at=f"{DAY}T09:00:00+00:00")
    noon = datetime(2026, 9, 18, 12, tzinfo=UTC)
    daily = next(b for b in budget_status(books, noon)["budgets"] if b["period"] == "DAILY")
    assert daily["spent_usd"] == "9" and daily["state"] == "WARNING"

    invoice(books, external_reference="RW-cheaper", amount="4.50")
    daily = next(b for b in budget_status(books, noon)["budgets"] if b["period"] == "DAILY")
    assert daily["spent_usd"] == "4.5" and daily["state"] == "OK", (
        "the estimate was dearer than the bill; the day is not spent twice"
    )


def test_a_failed_render_the_vendor_did_charge_for_is_reconciled_like_any_estimate(books):
    estimate(
        books,
        "render:c:failed:scene:1:motion",
        "6.00",
        at=f"{DAY}T08:00:00+00:00",
        attribution={"failed": True},
        failed=True,
    )
    with Session(books) as session:
        assert spend_since(session, START)["failed_render_usd"] == "6"
    answer = invoice(books, external_reference="RW-failed", amount="6")
    assert answer["matched"] == 1
    with Session(books) as session:
        after = spend_since(session, START)
    assert after["spent_usd"] == "6" and after["failed_render_usd"] == "0", (
        "the failed estimate is paid for by the invoice, not counted beside it"
    )


# ------------------------------------------------------------------- one invoice, once


def test_the_same_command_twice_is_one_invoice_and_a_different_figure_is_a_conflict(books):
    from app.services import CommandConflict

    estimate(books, "render:d:scene:1:motion", "2.00", at=f"{DAY}T10:00:00+00:00")
    command_id = uuid4()
    first = invoice(books, command_id=command_id, external_reference="RW-once", amount="2.10")
    again = invoice(books, command_id=command_id, external_reference="RW-once", amount="2.10")
    assert again == first, "a retry returns the original answer"
    with pytest.raises(CommandConflict):
        invoice(books, command_id=command_id, external_reference="RW-once", amount="9.99")
    with Session(books) as session:
        assert len(session.scalars(select(ProviderReconciliation)).all()) == 1
        assert len([r for r in session.scalars(select(ProviderCostRecord)) if r.status == "BILLED"])


def test_the_same_vendor_reference_cannot_be_reconciled_twice(books):
    estimate(books, "render:e:scene:1:motion", "1.00", at=f"{DAY}T10:00:00+00:00")
    invoice(books, external_reference="RW-dup", amount="1.00")
    estimate(books, "render:e:scene:2:motion", "1.00", at=f"{DAY}T11:00:00+00:00")
    with pytest.raises(EconomyError, match="RW-dup"):
        invoice(books, external_reference="RW-dup", amount="1.00")


# --------------------------------------------------------------- the version he replaces


def test_a_stale_expected_version_is_refused_and_a_correct_one_reverses_the_first_bill(books):
    estimate(books, "render:f:scene:1:motion", "5.00", at=f"{DAY}T10:00:00+00:00")
    first = invoice(books, external_reference="RW-v1", amount="5.50")
    assert first["version"] == 1 and first["active"] is True

    with pytest.raises(EconomyError, match="versiunea"):
        invoice(books, external_reference="RW-v9", amount="4.00", expected_version=9)
    # And the same period asked about again without naming a version is refused too: an
    # invoice he did not mean to replace is not replaced by accident.
    with pytest.raises(EconomyError, match="versiunea"):
        invoice(books, external_reference="RW-v2", amount="4.00")

    second = invoice(books, external_reference="RW-v2", amount="4.00", expected_version=1)
    assert second["version"] == 2 and second["replaces"] == first["id"]
    assert second["matched"] == 1, "the estimate the first invoice covered is re-adopted"
    assert second["reversal_transaction_id"], "the first bill is reversed, never edited"

    with Session(books) as session:
        rows = {r.external_reference: r for r in session.scalars(select(ProviderCostRecord))}
        assert rows["RW-v1"].reconciled_at is not None, "the superseded bill stops counting"
        assert rows["RW-v2"].reconciled_at is None
        first_row = session.get(ProviderReconciliation, first["id"])
        assert first_row.active is False and first_row.replaced_at
        after = spend_since(session, START)
    assert after["spent_usd"] == "4", "the corrected figure, once"
    assert trial_balance(books)["balanced"] is True
    assert treasury_snapshot(books)["spendable"]["amount"] == "-4"


# ------------------------------------------------------------- what it could not match


def test_what_the_invoice_could_not_match_is_reported_by_name(books):
    estimate(books, "render:g:scene:1:motion", "2.00", at=f"{DAY}T10:00:00+00:00")
    # A cost the studio already billed directly: real money, not an estimate to replace.
    record_provider_cost(
        books,
        provider="runway",
        external_reference="RW-direct",
        status="BILLED",
        amount="1.00",
    )
    with Session(books) as session, session.begin():
        session.scalars(
            select(ProviderCostRecord).where(ProviderCostRecord.external_reference == "RW-direct")
        ).one().recorded_at = f"{DAY}T10:30:00+00:00"

    answer = invoice(books, external_reference="RW-partial", amount="2.20")
    assert answer["matched"] == 1
    reported = answer["unmatched"]
    assert [u["external_reference"] for u in reported] == ["RW-direct"]
    assert "facturat" in reported[0]["reason"] and reported[0]["vr"] == "1"
    with Session(books) as session:
        direct = session.scalars(
            select(ProviderCostRecord).where(ProviderCostRecord.external_reference == "RW-direct")
        ).one()
        assert direct.reconciled_at is None, "never silently kept, never silently dropped"
        after = spend_since(session, START)
    assert after["spent_usd"] == "3.2", "the invoice plus the direct bill it does not cover"


def test_an_invoice_that_matches_nothing_says_so_and_is_still_recorded(books):
    answer = invoice(books, scope="CORRELATION", correlation="render-nobody-knows", amount="3")
    assert answer["matched"] == 0 and answer["matched_vr"] == "0"
    assert answer["difference_vr"] == "3"
    assert len(answer["unmatched"]) == 1 and answer["unmatched"][0]["cost_id"] is None
    assert "nicio estimare" in answer["unmatched"][0]["reason"].lower()
    with Session(books) as session:
        assert spend_since(session, START)["spent_usd"] == "3", (
            "the vendor billed; the books say so even when nothing explains it"
        )


def test_an_invoice_for_one_render_touches_only_that_render(books):
    estimate(
        books,
        "render:h:scene:1:motion",
        "1.50",
        at=f"{DAY}T10:00:00+00:00",
        attribution={"render_job_id": "h", "scene_index": 1},
    )
    estimate(
        books,
        "render:i:scene:1:motion",
        "2.50",
        at=f"{DAY}T10:05:00+00:00",
        attribution={"render_job_id": "i", "scene_index": 1},
    )
    answer = invoice(books, scope="CORRELATION", correlation="h", amount="1.60")
    assert answer["matched"] == 1 and answer["matched_vr"] == "1.5"
    with Session(books) as session:
        after = spend_since(session, START)
    assert after["spent_usd"] == "4.1", "1.60 billed for h, 2.50 still estimated for i"


# ------------------------------------------------------------------- shape and record


def test_an_invoice_names_its_bounds_and_leaves_an_event(books):
    with pytest.raises(EconomyError, match="perioad"):
        invoice(books, period_end=None)
    with pytest.raises(EconomyError, match="perioad"):
        invoice(books, period_start=END, period_end=START)
    with pytest.raises(EconomyError, match="corela"):
        invoice(books, scope="CORRELATION", correlation=None)

    estimate(books, "render:j:scene:1:motion", "1.00", at=f"{DAY}T10:00:00+00:00")
    answer = invoice(books, external_reference="RW-event", amount="1.25")
    with Session(books) as session:
        event = session.scalars(
            select(DomainEvent).where(
                DomainEvent.event_type == "economy.reconciliation_recorded",
                DomainEvent.aggregate_id == answer["id"],
            )
        ).one()
    assert event.payload["billed_vr"] == "1.25" and event.payload["matched"] == 1
    assert event.payload["provider"] == "runway"
    assert list_reconciliations(books)[0]["id"] == answer["id"]


def test_the_owner_is_the_only_hand_that_reconciles(books, client, headers):
    estimate(books, "render:k:scene:1:motion", "2.00", at=f"{DAY}T10:00:00+00:00")
    body = {
        "command_id": str(uuid4()),
        "provider": "runway",
        "external_reference": "RW-http",
        "amount": "2.40",
        "scope": "PERIOD",
        "period_start": START,
        "period_end": END,
    }
    assert client.put("/api/v1/economy/reconciliations", json=body).status_code == 401
    answer = client.put("/api/v1/economy/reconciliations", headers=headers, json=body)
    assert answer.status_code == 200 and answer.json()["matched"] == 1
    assert client.put("/api/v1/economy/reconciliations", headers=headers, json=body).json() == (
        answer.json()
    ), "a retry is the same invoice"
    stale = client.put(
        "/api/v1/economy/reconciliations",
        headers=headers,
        json={**body, "command_id": str(uuid4()), "external_reference": "RW-http-2"},
    )
    assert stale.status_code == 409, "the period already carries version 1"
    listed = client.get("/api/v1/economy/reconciliations", headers=headers).json()
    assert [r["external_reference"] for r in listed["reconciliations"]] == ["RW-http"]
