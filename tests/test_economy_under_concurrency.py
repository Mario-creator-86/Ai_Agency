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


# --------------------------------------------------------------------------- reservations


def test_two_films_cannot_both_reserve_the_last_ten_dollars(books):
    """Read-then-decide on the budget, pressed by simultaneous callers.

    `may_spend` answered from a snapshot, so two films asked together were both told the
    last ten dollars were free. A reservation is decided inside the writing transaction,
    behind the write lock, so the second caller reads the first one's hold.
    """
    from app.economy.budget import (
        BudgetCommand,
        may_spend,
        release_reservation,
        reserve_spend,
        set_budget,
    )

    set_budget(books, BudgetCommand(period="DAILY", limit_usd="10"))
    held: list[dict] = []
    lock = threading.Lock()

    def reserve() -> None:
        verdict = reserve_spend(books, 10_000_000, "film", str(uuid4()))
        if not verdict["allowed"]:
            raise EconomyError(verdict["reason"])
        with lock:
            held.append(verdict)

    outcomes = _race(reserve)

    assert outcomes.count("accepted") == 1, outcomes
    assert not [o for o in outcomes if o.startswith("error:")], outcomes
    assert len(held) == 1 and held[0]["reservation_id"]
    # The hold counts like a cost: one more cent is refused while it stands, and the
    # refusal says what is held rather than pretending it was spent.
    refused = may_spend(books, 10_000)
    assert not refused["allowed"] and "rezerva" in refused["reason"]
    # Let go, the money is free again; a second release is a no-op, not a second refund.
    assert release_reservation(books, held[0]["reservation_id"], "film not made")["released"]
    assert not release_reservation(books, held[0]["reservation_id"], "again")["released"]
    assert may_spend(books, 10_000_000)["allowed"]


def test_a_settled_reservation_stops_counting_once_the_real_cost_is_in_the_books(books):
    from app.economy.budget import (
        BudgetCommand,
        budget_status,
        reserve_spend,
        set_budget,
        settle_reservation,
    )
    from app.economy.services import record_provider_cost

    set_budget(books, BudgetCommand(period="DAILY", limit_usd="10"))
    hold = reserve_spend(books, 8_000_000, "film", str(uuid4()))
    assert hold["allowed"]
    daily = budget_status(books)["budgets"][0]
    assert (daily["reserved_usd"], daily["remaining_usd"], daily["state"]) == ("8", "2", "WARNING")
    record_provider_cost(
        books, provider="runway", external_reference="task-1", status="ESTIMATED", amount="3.00"
    )
    settled = settle_reservation(books, hold["reservation_id"], settled_reference="render:job-1")
    assert settled["status"] == "SETTLED"
    daily = budget_status(books)["budgets"][0]
    assert (daily["spent_usd"], daily["reserved_usd"], daily["remaining_usd"]) == ("3", "0", "7")


def test_a_reservation_older_than_the_ttl_is_released_by_the_watchdogs_hand(books):
    from datetime import UTC, datetime, timedelta

    from app.economy.budget import (
        BudgetCommand,
        may_spend,
        release_stale_reservations,
        reserve_spend,
        set_budget,
    )
    from app.economy.models import SpendReservation
    from sqlalchemy.orm import Session

    set_budget(books, BudgetCommand(period="DAILY", limit_usd="10"))
    fresh = reserve_spend(books, 4_000_000, "film A", str(uuid4()))
    stale = reserve_spend(books, 4_000_000, "film B", str(uuid4()))
    assert fresh["allowed"] and stale["allowed"]
    assert not may_spend(books, 3_000_000)["allowed"]
    with Session(books) as session, session.begin():
        row = session.get(SpendReservation, stale["reservation_id"])
        row.reserved_at = (datetime.now(UTC) - timedelta(hours=7)).isoformat()

    swept = release_stale_reservations(books, ttl_seconds=6 * 3600)

    assert swept["released"] == [stale["reservation_id"]]
    assert may_spend(books, 3_000_000)["allowed"], "four dollars held, six free"
    assert release_stale_reservations(books, ttl_seconds=6 * 3600)["released"] == []
    with Session(books) as session:
        row = session.get(SpendReservation, stale["reservation_id"])
        assert row.status == "RELEASED" and "watchdog" in (row.settled_reference or "")
