"""The money invariants, pressed by simultaneous callers rather than sequential ones.

Every rule in `backend/app/economy/services.py` is enforced by reading a row and then deciding.
Read-then-decide is exactly the shape that breaks when two callers do it at once, and the cost of
it breaking here is money that never existed. These tests fire several threads at the same
operation through the same engine and require the invariant to survive:

  * one verified dollar becomes one VR$ exactly once;
  * one payout is recorded once, however many times it arrives;
  * a transaction is reversed once, so a chargeback cannot be applied twice.

They pass today because SQLite serialises writers and each check sits inside the writing
transaction. That is a property of the code, not an accident of timing, and it is worth a test
that would notice if either half changed.
"""

from __future__ import annotations

import threading
from uuid import uuid4

import pytest
from app.economy.services import (
    EconomyError,
    mint_from_evidence,
    record_owner_funding,
    record_revenue_evidence,
    reverse_transaction,
    seed_chart_of_accounts,
    treasury_snapshot,
    trial_balance,
)


def _race(work, attempts: int = 6) -> list[str]:
    """Run `work` from several threads released at the same instant."""
    outcomes: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(attempts)

    def attempt() -> None:
        barrier.wait()
        try:
            work()
            result = "accepted"
        except EconomyError:
            result = "refused"
        except Exception as exc:  # noqa: BLE001
            result = f"error:{type(exc).__name__}"
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=attempt) for _ in range(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes


@pytest.fixture
def books(engine):
    seed_chart_of_accounts(engine)
    return engine


def _settled(engine, amount: str = "500.00") -> dict:
    return record_revenue_evidence(
        engine,
        source="YOUTUBE",
        external_reference=f"PAY-{uuid4().hex[:10]}",
        status="SETTLED",
        amount=amount,
        currency="USD",
    )


def test_one_payout_mints_once_however_many_callers_arrive_together(books):
    evidence = _settled(books, "500.00")

    outcomes = _race(lambda: mint_from_evidence(books, evidence["id"]))

    assert outcomes.count("accepted") == 1, outcomes
    assert not [o for o in outcomes if o.startswith("error:")], outcomes
    assert treasury_snapshot(books)["spendable"]["amount"] == "500"
    assert trial_balance(books)["balanced"] is True


def test_one_payout_is_recorded_once_however_many_times_it_arrives(books):
    reference = f"PAY-{uuid4().hex[:10]}"

    def record() -> None:
        record_revenue_evidence(
            books,
            source="YOUTUBE",
            external_reference=reference,
            status="SETTLED",
            amount="120.00",
            currency="USD",
        )

    outcomes = _race(record)

    assert outcomes.count("accepted") == 1, outcomes
    assert trial_balance(books)["balanced"] is True


def test_a_chargeback_reverses_once(books):
    evidence = _settled(books, "300.00")
    minted = mint_from_evidence(books, evidence["id"])

    outcomes = _race(
        lambda: reverse_transaction(books, minted["transaction_id"], reason="chargeback")
    )

    assert outcomes.count("accepted") == 1, outcomes
    # One mint, one reversal: the money is gone exactly once, not several times over.
    assert treasury_snapshot(books)["spendable"]["amount"] == "0"
    assert trial_balance(books)["balanced"] is True


def test_a_replayed_funding_command_funds_the_company_once(books):
    """A retried POST must not inject the Owner's money twice.

    `command_id` used to serve only as a correlation id, so replaying one request — a double
    submit, a proxy retry, a client that never saw the response — posted a second contribution
    and a second ledger transaction. It now returns the original answer instead.
    """
    command_id = str(uuid4())

    def fund() -> dict:
        return record_owner_funding(
            books,
            funding_type="CAPITAL_CONTRIBUTION",
            amount="10000",
            currency="USD",
            command_id=command_id,
        )

    first = fund()
    outcomes = _race(fund)

    assert outcomes == ["accepted"] * len(outcomes), outcomes
    # Every replay returned the original record rather than creating another.
    assert fund()["id"] == first["id"]
    assert treasury_snapshot(books)["spendable"]["amount"] == "10000"
    assert trial_balance(books)["balanced"] is True


def test_the_same_command_id_with_different_money_is_refused(books):
    """Two different intents cannot share one identity; guessing which was meant is not on offer."""
    from app.services import CommandConflict

    command_id = str(uuid4())
    record_owner_funding(
        books,
        funding_type="CAPITAL_CONTRIBUTION",
        amount="500",
        currency="USD",
        command_id=command_id,
    )
    with pytest.raises(CommandConflict):
        record_owner_funding(
            books,
            funding_type="CAPITAL_CONTRIBUTION",
            amount="900",
            currency="USD",
            command_id=command_id,
        )
    assert treasury_snapshot(books)["spendable"]["amount"] == "500"


def test_two_deliberate_contributions_of_the_same_amount_both_count(books):
    """Idempotency keys on the command, not on the money: funding twice on purpose is allowed."""
    for _ in range(2):
        record_owner_funding(
            books,
            funding_type="CAPITAL_CONTRIBUTION",
            amount="250",
            currency="USD",
            command_id=str(uuid4()),
        )
    assert treasury_snapshot(books)["spendable"]["amount"] == "500"
