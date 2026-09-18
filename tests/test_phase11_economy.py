"""Phase 11 — real financial evidence and the VR$ ledger built from it.

The acceptance criteria for the economy are unusually blunt (`26_MASTER_ACCEPTANCE_CRITERIA.md`
§"V5 Economy"), because the failure modes are the kind that quietly invent money:

  * one settled dollar must produce exactly one VR$, once;
  * a forecast must never become spendable;
  * a reversal must post, not delete;
  * the books must always balance.

These tests exist to make each of those hard to break by accident. Most of them are about what
the ledger refuses.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.economy.models import LedgerEntry, LedgerTransaction, RevenueEvidence
from app.economy.services import (
    EconomyError,
    bill_provider_cost,
    format_micros,
    list_transactions,
    mint_from_evidence,
    record_fx_snapshot,
    record_owner_funding,
    record_provider_cost,
    record_revenue_evidence,
    reverse_transaction,
    seed_chart_of_accounts,
    settle_evidence,
    to_micros,
    treasury_snapshot,
    trial_balance,
)
from app.models import DomainEvent
from sqlalchemy import select
from sqlalchemy.orm import Session


@pytest.fixture
def books(engine):
    """A studio with its chart of accounts and an empty ledger."""
    seed_chart_of_accounts(engine)
    return engine


def settled(engine, amount="734.22", reference=None, source="YOUTUBE", **kw):
    return record_revenue_evidence(
        engine,
        source=source,
        external_reference=reference or f"PAY-{uuid4().hex[:10]}",
        status="SETTLED",
        amount=amount,
        currency=kw.pop("currency", "USD"),
        **kw,
    )


def spendable(engine) -> str:
    return treasury_snapshot(engine)["spendable"]["amount"]


# --------------------------------------------------------------------------- money handling --


def test_amounts_survive_as_exact_integers():
    """Money is never a float: a cent that cannot be represented is a ledger that drifts."""
    assert to_micros("734.22") == 734_220_000
    assert to_micros("0.000001") == 1
    assert to_micros(5) == 5_000_000
    # Half rounds away from zero at the last micro rather than truncating value away.
    assert to_micros("0.0000005") == 1
    assert format_micros(734_220_000) == "734.22"
    assert format_micros(0) == "0"
    assert format_micros(-25_000_000) == "-25"
    for rubbish in ("abc", "1.2.3", "12,50"):
        with pytest.raises(EconomyError):
            to_micros(rubbish)


def test_seeding_accounts_is_idempotent_and_leaves_the_ledger_empty(engine):
    first = seed_chart_of_accounts(engine)
    assert first > 0
    assert seed_chart_of_accounts(engine) == 0, "seeding twice must not duplicate accounts"
    treasury = treasury_snapshot(engine)
    assert treasury["spendable"]["amount"] == "0"
    assert treasury["trial_balance"]["balanced"] is True


# ------------------------------------------------------------------------- the 1:1 rule --


def test_one_settled_dollar_becomes_exactly_one_vr_dollar_once(books):
    evidence = settled(books, amount="734.22", reference="PAY-8813")
    assert evidence["minted"] is False
    assert spendable(books) == "0", "recording evidence must not create VR$"

    result = mint_from_evidence(books, evidence["id"])
    assert result["evidence"]["minted"] is True
    assert spendable(books) == "734.22"

    # The same payout cannot be minted again, however many times it is retried.
    with pytest.raises(EconomyError, match="already been minted"):
        mint_from_evidence(books, evidence["id"])
    assert spendable(books) == "734.22"


def test_the_same_payout_cannot_be_recorded_twice(books):
    settled(books, amount="100", reference="PAY-DUP")
    with pytest.raises(EconomyError, match="already recorded"):
        settled(books, amount="100", reference="PAY-DUP")
    with pytest.raises(EconomyError, match="already recorded"):
        settled(books, amount="999999", reference="PAY-DUP")
    # A different source may legitimately use the same reference string.
    settled(books, amount="100", reference="PAY-DUP", source="DONATION")


def test_minting_credits_the_revenue_account_for_the_source(books):
    evidence = settled(books, amount="50", source="SPONSORSHIP")
    mint_from_evidence(books, evidence["id"])
    posting = list_transactions(books)[0]
    assert posting["kind"] == "MINT"
    assert {line["account"] for line in posting["lines"]} == {"1000", "4020"}


# ------------------------------------------------------- forecasts are never spendable --


@pytest.mark.parametrize("status", ["ESTIMATED", "PENDING_PAYOUT"])
def test_unsettled_evidence_can_never_be_minted_or_spent(books, status):
    evidence = record_revenue_evidence(
        books,
        source="YOUTUBE",
        external_reference=f"EST-{status}",
        status=status,
        amount="5000",
        currency="USD",
    )
    with pytest.raises(EconomyError, match="never spendable|Only settled"):
        mint_from_evidence(books, evidence["id"])
    assert spendable(books) == "0"

    treasury = treasury_snapshot(books)
    # It is reported, clearly labelled, and excluded from anything spendable.
    reported = {row["money_class"]: row for row in treasury["not_spendable"]}
    key = "FORECAST" if status == "ESTIMATED" else "PENDING_EXTERNAL"
    assert reported[key]["amount"] == "5000"
    assert reported[key]["spendable"] is False
    assert all(row["spendable"] is False for row in treasury["not_spendable"])


def test_settling_then_minting_is_the_only_route_from_forecast_to_cash(books):
    evidence = record_revenue_evidence(
        books,
        source="YOUTUBE",
        external_reference="PAY-LATER",
        status="PENDING_PAYOUT",
        amount="120.50",
        currency="USD",
    )
    assert spendable(books) == "0"
    settle_evidence(books, evidence["id"])
    assert spendable(books) == "0", "settling alone still mints nothing"
    mint_from_evidence(books, evidence["id"])
    assert spendable(books) == "120.5"


# --------------------------------------------------------------------------- reversals --


def test_a_chargeback_posts_a_mirror_and_never_deletes_the_original(books):
    evidence = settled(books, amount="734.22", reference="PAY-CB")
    minted = mint_from_evidence(books, evidence["id"])
    reverse_transaction(books, minted["transaction_id"], reason="Platform reversed the payout")

    assert spendable(books) == "0"
    with Session(books) as session:
        original = session.get(LedgerTransaction, minted["transaction_id"])
        assert original is not None, "the original posting must survive its own reversal"
        assert session.get(RevenueEvidence, evidence["id"]).status == "REVERSED"
        kinds = session.scalars(select(LedgerTransaction.kind)).all()
    assert sorted(kinds) == ["MINT", "REVERSAL"]
    assert trial_balance(books)["balanced"] is True


def test_a_reversal_happens_at_most_once_and_cannot_itself_be_reversed(books):
    evidence = settled(books, amount="10", reference="PAY-ONCE")
    minted = mint_from_evidence(books, evidence["id"])
    first = reverse_transaction(books, minted["transaction_id"], reason="chargeback")

    with pytest.raises(EconomyError, match="already been reversed"):
        reverse_transaction(books, minted["transaction_id"], reason="again")
    with pytest.raises(EconomyError, match="cannot itself be reversed"):
        reverse_transaction(books, first["reversal_transaction_id"], reason="undo the undo")
    assert spendable(books) == "0"


def test_a_reversal_needs_a_reason(books):
    evidence = settled(books, amount="10")
    minted = mint_from_evidence(books, evidence["id"])
    with pytest.raises(EconomyError, match="needs a reason"):
        reverse_transaction(books, minted["transaction_id"], reason="   ")


def test_a_reversal_removes_exactly_what_it_posted_and_nothing_else(books):
    small = settled(books, amount="20", reference="PAY-SMALL")
    big = settled(books, amount="500", reference="PAY-BIG")
    mint_from_evidence(books, small["id"])
    big_minted = mint_from_evidence(books, big["id"])
    assert spendable(books) == "520"
    reverse_transaction(books, big_minted["transaction_id"], reason="chargeback")
    assert spendable(books) == "20", "the small payout is untouched by the large one's reversal"
    assert trial_balance(books)["balanced"] is True


def test_a_chargeback_after_the_money_was_spent_shows_a_deficit_rather_than_hiding_it(books):
    evidence = settled(books, amount="500", reference="PAY-SPENT")
    minted = mint_from_evidence(books, evidence["id"])
    # The studio really spent most of it on model usage before the platform took the payout back.
    record_provider_cost(
        books,
        provider="openai",
        external_reference="INV-2026-08",
        status="BILLED",
        amount="480",
    )
    assert spendable(books) == "20"
    reverse_transaction(books, minted["transaction_id"], reason="platform chargeback")

    treasury = treasury_snapshot(books)
    assert treasury["spendable"]["amount"] == "-480"
    assert treasury["in_deficit"] is True
    assert treasury["trial_balance"]["balanced"] is True


# ----------------------------------------------------------------- the books must balance --


def test_every_posting_leaves_the_books_balanced(books):
    record_fx_snapshot(
        books,
        base_currency="EUR",
        quote_currency="USD",
        rate="1.08",
        source="ECB reference rate",
        observed_at="2026-09-10T12:00:00+00:00",
    )
    for index in range(6):
        evidence = settled(books, amount=f"{100 + index}.55", reference=f"PAY-{index}")
        mint_from_evidence(books, evidence["id"])
        assert trial_balance(books)["balanced"] is True

    record_owner_funding(books, funding_type="CAPITAL_CONTRIBUTION", amount="1000", currency="USD")
    record_owner_funding(
        books,
        funding_type="OWNER_LOAN",
        amount="2500",
        currency="USD",
        annual_rate_bps=500,
        maturity_date="2027-09-10",
    )
    assert trial_balance(books)["balanced"] is True
    assert treasury_snapshot(books)["trial_balance"]["difference"] == "0"


def test_an_unbalanced_or_malformed_posting_is_refused_before_anything_is_written(books):
    from app.economy.services import post_transaction

    with Session(books) as session, session.begin():
        with pytest.raises(EconomyError, match="do not equal credits"):
            post_transaction(
                session,
                kind="ADJUSTMENT",
                memo="unbalanced",
                lines=[("1000", 100, 0), ("4000", 0, 90)],
                correlation_id=str(uuid4()),
            )
        with pytest.raises(EconomyError, match="either a debit or a credit"):
            post_transaction(
                session,
                kind="ADJUSTMENT",
                memo="two-sided line",
                lines=[("1000", 100, 100)],
                correlation_id=str(uuid4()),
            )
        with pytest.raises(EconomyError, match="not in the chart of accounts"):
            post_transaction(
                session,
                kind="ADJUSTMENT",
                memo="unknown account",
                lines=[("9999", 100, 0), ("4000", 0, 100)],
                correlation_id=str(uuid4()),
            )
    with Session(books) as session:
        assert session.scalars(select(LedgerEntry)).all() == [], "a refusal must write nothing"


# ------------------------------------------------------------------------ multi-currency --


def test_a_foreign_amount_without_a_recorded_rate_is_refused_not_guessed(books):
    with pytest.raises(EconomyError, match="does not invent rates"):
        record_revenue_evidence(
            books,
            source="SPONSORSHIP",
            external_reference="INV-EUR-1",
            status="SETTLED",
            amount="100",
            currency="EUR",
        )


def test_a_conversion_cites_the_rate_it_used(books):
    fx = record_fx_snapshot(
        books,
        base_currency="EUR",
        quote_currency="USD",
        rate="1.08",
        source="ECB reference rate",
        observed_at="2026-09-10T12:00:00+00:00",
    )
    evidence = record_revenue_evidence(
        books,
        source="SPONSORSHIP",
        external_reference="INV-EUR-2",
        status="SETTLED",
        amount="100",
        currency="EUR",
        fx_snapshot_id=fx["id"],
    )
    assert evidence["original_amount"] == "100"
    assert evidence["original_currency"] == "EUR"
    assert evidence["usd"] == "108"
    assert evidence["fx_snapshot_id"] == fx["id"]
    mint_from_evidence(books, evidence["id"])
    assert spendable(books) == "108", "VR$ follows the converted USD value, not the face amount"


def test_a_usd_amount_refuses_an_irrelevant_rate(books):
    fx = record_fx_snapshot(
        books,
        base_currency="EUR",
        quote_currency="USD",
        rate="1.08",
        source="ECB",
        observed_at="2026-09-10T12:00:00+00:00",
    )
    with pytest.raises(EconomyError, match="needs no exchange rate"):
        record_revenue_evidence(
            books,
            source="OTHER",
            external_reference="USD-WITH-FX",
            status="SETTLED",
            amount="10",
            currency="USD",
            fx_snapshot_id=fx["id"],
        )


# ------------------------------------------------------------------------- Owner funding --


def test_contribution_and_loan_land_in_different_places_in_the_ledger(books):
    record_owner_funding(
        books, funding_type="CAPITAL_CONTRIBUTION", amount="1000", currency="USD", note="seed"
    )
    record_owner_funding(
        books,
        funding_type="OWNER_LOAN",
        amount="500",
        currency="USD",
        annual_rate_bps=650,
        maturity_date="2027-01-31",
    )
    treasury = treasury_snapshot(books)
    balances = {row["code"]: row["balance"] for row in treasury["accounts"]}
    assert balances["1000"] == "1500", "both increase cash"
    assert balances["3000"] == "1000", "the contribution is equity"
    assert balances["2000"] == "500", "the loan is a liability"
    debt = next(row for row in treasury["positions"] if row["money_class"] == "VR_DEBT")
    assert debt["amount"] == "500"
    assert debt["spendable"] is False


def test_a_loan_without_terms_and_a_contribution_with_them_are_both_refused(books):
    with pytest.raises(EconomyError, match="needs a rate and a maturity"):
        record_owner_funding(books, funding_type="OWNER_LOAN", amount="500", currency="USD")
    with pytest.raises(EconomyError, match="carries no rate or maturity"):
        record_owner_funding(
            books,
            funding_type="CAPITAL_CONTRIBUTION",
            amount="500",
            currency="USD",
            annual_rate_bps=100,
            maturity_date="2027-01-01",
        )


def test_owner_funding_never_claims_to_move_real_money(books):
    funding = record_owner_funding(
        books, funding_type="CAPITAL_CONTRIBUTION", amount="10", currency="USD"
    )
    assert funding["moves_real_money"] is False
    with Session(books) as session:
        event = session.scalar(
            select(DomainEvent).where(DomainEvent.event_type == "economy.owner_funding_recorded")
        )
    assert event.payload["moves_real_money"] is False


# ------------------------------------------------------------------------- audit trail --


def test_every_economic_act_leaves_an_event(books):
    evidence = settled(books, amount="42", reference="PAY-EVENT")
    minted = mint_from_evidence(books, evidence["id"])
    reverse_transaction(books, minted["transaction_id"], reason="chargeback")
    with Session(books) as session:
        types = session.scalars(
            select(DomainEvent.event_type).where(DomainEvent.event_type.like("economy.%"))
        ).all()
    assert "economy.evidence_recorded" in types
    assert "economy.vr_minted" in types
    assert "economy.evidence_reversed" in types
    assert types.count("economy.transaction_posted") == 2, "both the mint and its reversal"


def test_treasury_labels_every_figure_and_says_what_the_books_are_not(books):
    treasury = treasury_snapshot(books)
    assert treasury["unit"] == "VR$"
    assert treasury["anchor"] == "1 verified USD = 1 VR$"
    assert {row["label"] for row in treasury["positions"]} == {"VR VIRTUAL"}
    assert {row["label"] for row in treasury["not_spendable"]} == {"PENDING", "FORECAST"}
    assert "nu mișcă bani reali" in treasury["disclaimer"]


# --------------------------------------------------------------------------------- API --


def test_the_economy_api_is_owner_only(client):
    for path in ("/api/v1/economy/treasury", "/api/v1/economy/ledger", "/api/v1/economy/evidence"):
        assert client.get(path).status_code == 401
    assert client.post("/api/v1/economy/evidence", json={}).status_code == 401


def test_the_api_records_settles_mints_and_reverses(client, headers, engine):
    seed_chart_of_accounts(engine)
    created = client.post(
        "/api/v1/economy/evidence",
        headers=headers,
        json={
            "command_id": str(uuid4()),
            "source": "YOUTUBE",
            "external_reference": "PAY-API-1",
            "status": "PENDING_PAYOUT",
            "amount": "250.00",
            "currency": "USD",
        },
    )
    assert created.status_code == 200, created.text
    evidence_id = created.json()["id"]
    treasury = client.get("/api/v1/economy/treasury", headers=headers).json()
    assert treasury["spendable"]["amount"] == "0"

    # Minting a pending payout is refused by the API, not just by the service.
    refused = client.post(f"/api/v1/economy/evidence/{evidence_id}/mint", headers=headers)
    assert refused.status_code == 409
    assert "settled" in refused.json()["detail"].lower()

    client.post(f"/api/v1/economy/evidence/{evidence_id}/settle", headers=headers)
    minted = client.post(f"/api/v1/economy/evidence/{evidence_id}/mint", headers=headers)
    assert minted.status_code == 200
    treasury = client.get("/api/v1/economy/treasury", headers=headers).json()
    assert treasury["spendable"]["amount"] == "250"
    assert treasury["trial_balance"]["balanced"] is True

    transaction_id = minted.json()["transaction_id"]
    reversed_response = client.post(
        f"/api/v1/economy/ledger/{transaction_id}/reverse",
        headers=headers,
        json={"command_id": str(uuid4()), "reason": "platform chargeback"},
    )
    assert reversed_response.status_code == 200
    after = client.get("/api/v1/economy/treasury", headers=headers).json()
    assert after["spendable"]["amount"] == "0"


def test_the_api_rejects_a_malformed_amount_before_it_reaches_the_ledger(client, headers, engine):
    seed_chart_of_accounts(engine)
    response = client.post(
        "/api/v1/economy/evidence",
        headers=headers,
        json={
            "command_id": str(uuid4()),
            "source": "YOUTUBE",
            "external_reference": "PAY-BAD",
            "status": "SETTLED",
            "amount": "1,000.00",
            "currency": "USD",
        },
    )
    assert response.status_code == 422


def test_there_is_no_route_that_spends_or_pays_anything(client):
    """The procurement path must contain no external checkout command (`26_MASTER…` §Economy)."""
    # The OpenAPI schema is the documented surface an auditor would read, and it lists every
    # mounted path — unlike `app.routes`, where included routers are opaque composites.
    documented = client.app.app.openapi()["paths"]
    economy = sorted(path for path in documented if "/economy" in path)
    assert economy, "the economy routes should be mounted"
    forbidden = ("pay", "checkout", "purchase", "transfer", "withdraw", "charge", "spend")
    assert not [p for p in economy if any(word in p.lower() for word in forbidden)], economy
    # And nothing anywhere else in the API offers to move real money either.
    assert not [p for p in documented if "checkout" in p.lower() or "payment" in p.lower()]


# --------------------------------------------------------------------------- provider costs --


def test_an_estimated_cost_is_tracked_but_never_posted(books):
    evidence = settled(books, amount="100", reference="PAY-COST")
    mint_from_evidence(books, evidence["id"])
    cost = record_provider_cost(
        books,
        provider="ollama-cloud",
        external_reference="USAGE-2026-09-10",
        status="ESTIMATED",
        amount="12.34",
        attribution={"agent": "researcher"},
    )
    assert cost["posted"] is False
    assert cost["transaction_id"] is None
    assert spendable(books) == "100", "an estimate is not a bill and must not move cash"

    treasury = treasury_snapshot(books)
    assert treasury["unbilled_provider_costs"]["amount"] == "12.34"
    assert treasury["unbilled_provider_costs"]["posted"] is False

    billed = bill_provider_cost(books, cost["id"])
    assert billed["posted"] is True
    assert spendable(books) == "87.66"
    assert treasury_snapshot(books)["unbilled_provider_costs"]["amount"] == "0"


def test_the_same_invoice_cannot_charge_the_studio_twice(books):
    record_provider_cost(
        books, provider="openai", external_reference="INV-9", status="BILLED", amount="10"
    )
    with pytest.raises(EconomyError, match="already recorded"):
        record_provider_cost(
            books, provider="openai", external_reference="INV-9", status="BILLED", amount="10"
        )
    # A different provider may reuse the reference string.
    record_provider_cost(
        books, provider="elevenlabs", external_reference="INV-9", status="BILLED", amount="3"
    )
    assert spendable(books) == "-13"


def test_a_posted_invoice_cannot_be_posted_again(books):
    cost = record_provider_cost(
        books, provider="openai", external_reference="INV-10", status="BILLED", amount="5"
    )
    with pytest.raises(EconomyError, match="already been posted"):
        bill_provider_cost(books, cost["id"])
    assert spendable(books) == "-5"


def test_a_billed_cost_debits_the_provider_expense_account(books):
    record_provider_cost(
        books, provider="openai", external_reference="INV-11", status="BILLED", amount="7.50"
    )
    posting = list_transactions(books)[0]
    assert posting["kind"] == "PROVIDER_COST"
    lines = {line["account"]: line for line in posting["lines"]}
    assert lines["5000"]["debit"] == "7.5"
    assert lines["1000"]["credit"] == "7.5"
    assert trial_balance(books)["balanced"] is True


# --------------------------------------------------------------------------- provider prices --


def test_prices_are_set_only_by_the_owner_versioned_and_replayed_safely(client, headers, engine):
    """`PUT /economy/prices` follows the budget command: Owner-only, kept, versioned."""
    body = {
        "command_id": str(uuid4()),
        "provider_kind": "ollama",
        "resource": "gpt-oss:120b-cloud",
        "unit": "per_1m_input_tokens",
        "usd": "0.15",
        "notes": "Ollama Cloud pricing page, 2026-09-18",
    }
    assert client.put("/api/v1/economy/prices", json=body).status_code == 401
    assert client.get("/api/v1/economy/prices").status_code == 401

    first = client.put("/api/v1/economy/prices", headers=headers, json=body)
    assert first.status_code == 200, first.text
    assert (first.json()["version"], first.json()["provenance"]) == (1, "OWNER")
    # The same command again is a retry, not a second price.
    assert client.put("/api/v1/economy/prices", headers=headers, json=body).json() == first.json()
    # The same command with another figure is a conflict.
    conflict = client.put("/api/v1/economy/prices", headers=headers, json={**body, "usd": "0.20"})
    assert conflict.status_code == 409
    second = client.put(
        "/api/v1/economy/prices",
        headers=headers,
        json={**body, "command_id": str(uuid4()), "usd": "0.20", "expected_version": 1},
    )
    assert second.status_code == 200 and second.json()["version"] == 2
    stale = client.put(
        "/api/v1/economy/prices",
        headers=headers,
        json={**body, "command_id": str(uuid4()), "usd": "0.30", "expected_version": 1},
    )
    assert stale.status_code == 409
    listed = client.get("/api/v1/economy/prices", headers=headers).json()["prices"]
    assert [(p["resource"], p["usd"], p["version"]) for p in listed] == [
        ("gpt-oss:120b-cloud", "0.2", 2)
    ]
    # A unit the books do not know, or a provenance nobody can vouch for, never reaches them.
    unit = client.put("/api/v1/economy/prices", headers=headers, json={**body, "unit": "per_pound"})
    assert unit.status_code == 422
    guessed = client.put(
        "/api/v1/economy/prices", headers=headers, json={**body, "provenance": "GUESSED"}
    )
    assert guessed.status_code == 422


def test_a_failed_render_cost_is_labelled_as_such_in_the_owners_list(books, client, headers):
    record_provider_cost(
        books,
        provider="elevenlabs",
        external_reference="render:j:failed:scene:1:voice",
        status="ESTIMATED",
        amount="0.30",
        attribution={"failed": True},
        failed=True,
    )
    listed = client.get("/api/v1/economy/provider-costs", headers=headers).json()["costs"]
    assert listed[0]["failed"] is True and "eșuată" in listed[0]["label"]
    # Still an estimate: never posted, nothing in the ledger.
    assert treasury_snapshot(books)["spendable"]["amount"] == "0"
    assert trial_balance(books)["balanced"] is True
