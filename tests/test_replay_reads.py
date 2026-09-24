"""Two reads the headquarters' «Reluarea zilei» needs from the studio's own record (W15).

The page replays the newest finished run from its events. Two things it could not read cheaply:

* where the run begins in the event log. The log is paged by sequence (`/events?after=`), so the
  page bisected it: about twelve one-event probes before the first page on the Owner's data.
  `/events?since=<instant>` answers the first page at once: every event from the first one
  stamped at or after the instant, in sequence order, found through an index on the stamp.
* what the Treasury and the tokens plate said at a moment of that run. The live treasury is not
  the treasury of that night, so the replay's walls said «—». `/economy/as-of?at=…` answers, for
  each instant asked, the spendable balance from the ledger's own postings up to it, and the
  day's spend and tokens up to it against the budget that was active then: one request for all
  the moments a replay crosses, read with a fixed number of indexed queries.

An older studio ignores the unknown `since` parameter and answers the log from its start, so the
answer names the instant it was read from; the page believes a page only when it does.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.agents.models import Agent, AgentRun, ModelRecord, ProviderRecord, Role
from app.economy.as_of import economy_as_of
from app.economy.budget import BudgetCommand, budget_status, set_budget
from app.economy.models import (
    LedgerTransaction,
    ProviderCostRecord,
    SpendingBudget,
    SpendReservation,
)
from app.economy.services import (
    record_owner_funding,
    record_provider_cost,
    seed_chart_of_accounts,
    treasury_snapshot,
)
from app.models import DomainEvent
from app.services import read_events, utc_now
from sqlalchemy import event, select, update
from sqlalchemy.orm import Session

# --------------------------------------------------------------------------- the event log --


def stamp_events(engine, stamps: list[str]) -> list[int]:
    """Append one event per stamp, in this order, stamped so (the log is immutable once
    written, so the stamp is given at the write): their sequences."""
    sequences = []
    with Session(engine) as session, session.begin():
        for i, when in enumerate(stamps):
            row = DomainEvent(
                event_id=str(uuid4()),
                event_type="test.replay_probe",
                timestamp=when,
                aggregate_type="test",
                aggregate_id=str(uuid4()),
                aggregate_version=1,
                correlation_id=str(uuid4()),
                causation_id=None,
                schema_version=1,
                visibility="OWNER",
                payload={"i": i},
            )
            session.add(row)
            session.flush()
            sequences.append(row.sequence)
    return sequences


def test_since_answers_from_the_first_event_stamped_at_or_after_the_instant(
    client, headers, engine
):
    seqs = stamp_events(
        engine,
        [
            "2030-09-12T20:40:00+00:00",
            "2030-09-12T20:47:59.900000+00:00",
            "2030-09-12T20:48:06.030353+00:00",
            "2030-09-12T20:48:07+00:00",
            "2030-09-12T20:59:45+00:00",
        ],
    )
    page = client.get(
        "/api/v1/events",
        params={"since": "2030-09-12T23:48:01+03:00", "limit": 2},
        headers=headers,
    ).json()
    # the instant is read in UTC, and the answer names it, so a page can tell it was understood
    assert page["since"] == "2030-09-12T20:48:01+00:00"
    assert [e["sequence"] for e in page["events"]] == seqs[2:4]
    assert page["has_more"] is True
    assert page["next_cursor"] == seqs[3]
    # the next page is the ordinary one: after the cursor
    rest = client.get(
        "/api/v1/events", params={"after": page["next_cursor"], "limit": 300}, headers=headers
    ).json()
    assert [e["sequence"] for e in rest["events"]] == seqs[4:]


def test_an_event_stamped_out_of_order_is_not_skipped(client, headers, engine):
    """Two writers can commit a moment apart in the other order; nothing after the instant is
    lost: the page starts from the lowest sequence stamped at or after it."""
    seqs = stamp_events(
        engine,
        ["2030-09-12T20:48:09+00:00", "2030-09-12T20:48:08+00:00", "2030-09-12T20:48:10+00:00"],
    )
    page = client.get(
        "/api/v1/events",
        params={"since": "2030-09-12T20:48:08.500000+00:00", "limit": 10},
        headers=headers,
    ).json()
    assert [e["sequence"] for e in page["events"]][:3] == seqs


def test_since_past_the_newest_event_is_an_empty_page(client, headers, engine):
    stamp_events(engine, ["2030-09-12T20:48:09+00:00"])
    page = client.get(
        "/api/v1/events", params={"since": "2099-01-01T00:00:00Z"}, headers=headers
    ).json()
    assert page["events"] == []
    assert page["has_more"] is False
    assert page["since"] == "2099-01-01T00:00:00+00:00"


def test_since_refuses_what_is_not_an_instant(client, headers):
    for bad in ("yesterday", "2026-13-01T00:00:00Z", ""):
        response = client.get("/api/v1/events", params={"since": bad}, headers=headers)
        assert response.status_code == 422, bad


def test_the_log_without_since_answers_as_before(client, headers, engine):
    stamp_events(engine, ["2030-09-12T20:48:09+00:00"])
    page = client.get("/api/v1/events", params={"after": 0, "limit": 5}, headers=headers).json()
    assert "since" not in page
    assert page["events"][0]["sequence"] == 1


def test_since_is_one_indexed_query(engine):
    stamp_events(engine, [f"2030-09-12T20:{m:02d}:00+00:00" for m in range(10, 50)])
    statements: list[tuple[str, tuple]] = []

    def count(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if "domain_event" in statement and statement.lstrip().upper().startswith("SELECT"):
            statements.append((statement, tuple(parameters)))

    event.listen(engine, "before_cursor_execute", count)
    try:
        page = read_events(engine, 0, 3, "2030-09-12T20:30:00+00:00")
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert [e["timestamp"] for e in page["events"]][0] == "2030-09-12T20:30:00+00:00"
    # the reset line (maintenance.ledger_floor) is read as before; the page itself is one query
    pages = [(s, p) for s, p in statements if "timestamp >=" in s]
    assert len(pages) == 1, statements
    assert "ix_domain_event_timestamp" in query_plan(engine, *pages[0])


def query_plan(engine, statement: str, parameters: tuple) -> str:
    with engine.connect() as connection:
        rows = connection.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters)
        return " ".join(str(row[-1]) for row in rows.fetchall())


# --------------------------------------------------------------------------- the books --


@pytest.fixture
def books(engine):
    seed_chart_of_accounts(engine)
    return engine


def posted_at(engine, transaction_id: str, when: str) -> None:
    with Session(engine) as session, session.begin():
        session.execute(
            update(LedgerTransaction)
            .where(LedgerTransaction.id == transaction_id)
            .values(posted_at=when)
        )


def fund(engine, amount: str, when: str) -> None:
    result = record_owner_funding(
        engine, funding_type="CAPITAL_CONTRIBUTION", amount=amount, currency="USD"
    )
    posted_at(engine, result["transaction_id"], when)


def cost(engine, amount: str, when: str, *, status: str = "ESTIMATED") -> str:
    row = record_provider_cost(
        engine,
        provider="runway",
        external_reference=f"render:{uuid4()}",
        status=status,
        amount=amount,
        currency="USD",
    )
    with Session(engine) as session, session.begin():
        stored = session.get(ProviderCostRecord, row["id"])
        assert stored is not None
        stored.recorded_at = when
        if stored.transaction_id:
            session.get(LedgerTransaction, stored.transaction_id).posted_at = when  # type: ignore[union-attr]
    return row["id"]


def budget(engine, limit: str, when: str) -> None:
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd=limit))
    with Session(engine) as session, session.begin():
        session.execute(
            update(SpendingBudget).where(SpendingBudget.active.is_(True)).values(created_at=when)
        )


def an_agent(engine) -> str:
    with Session(engine) as session, session.begin():
        eid = session.scalars(select(DomainEvent).limit(1)).one().event_id
        role = Role(
            id=str(uuid4()),
            name="Researcher",
            mission="Find sources",
            allowed_task_types="gather_sources",
            prohibited_actions="",
            created_at=utc_now(),
            event_id=eid,
        )
        provider = ProviderRecord(
            id=str(uuid4()),
            name="local-ollama",
            provider_type="OLLAMA",
            base_url="http://127.0.0.1:11434",
            status="NOT_CONFIGURED",
            last_health_check=None,
            adapter_version="1.0.0",
            notes="",
            created_at=utc_now(),
            event_id=eid,
        )
        session.add_all([role, provider])
        session.flush()
        model = ModelRecord(
            id=str(uuid4()),
            provider_id=provider.id,
            model_name="m:latest",
            discovery_method="MANUALLY_CONFIGURED",
            context_length=None,
            last_verified=None,
            is_available=True,
            notes="",
        )
        session.add(model)
        session.flush()
        agent = Agent(
            id=str(uuid4()),
            display_name="Dr. Aris (Researcher)",
            role_id=role.id,
            provider_id=provider.id,
            model_id=model.id,
            lifecycle="ACTIVE",
            runtime_state="IDLE",
            cost_limit_per_task=None,
            max_concurrent_tasks=1,
            version=1,
            hired_at=utc_now(),
            terminated_at=None,
            event_id=eid,
        )
        session.add(agent)
        return agent.id


def run(engine, agent_id, started, finished, *, tokens=(0, 0), cost_vr=None, status="SUCCEEDED"):
    with Session(engine) as session, session.begin():
        session.add(
            AgentRun(
                id=str(uuid4()),
                agent_id=agent_id,
                task_type="gather_sources",
                objective="x",
                prompt_template_version="v1",
                model_name="m",
                provider_name="p",
                status=status,
                correlation_id=str(uuid4()),
                started_at=started,
                finished_at=finished,
                prompt_tokens=tokens[0],
                completion_tokens=tokens[1],
                cost_vr=cost_vr,
                context_json={},
            )
        )


def reading(engine, at: str) -> dict:
    return economy_as_of(engine, [at])["readings"][0]


def test_the_balance_at_a_moment_counts_only_what_was_posted_by_then(books):
    fund(books, "50", "2026-09-10T08:00:00+00:00")
    cost(books, "4.55", "2026-09-12T20:55:00+00:00", status="BILLED")
    before = reading(books, "2026-09-09T00:00:00+00:00")["treasury"]
    during = reading(books, "2026-09-12T20:50:00+00:00")["treasury"]
    after = reading(books, "2026-09-12T20:59:45+00:00")["treasury"]
    assert before["spendable"]["amount"] == "0"
    assert during["spendable"]["amount"] == "50"
    assert after["spendable"]["amount"] == "45.45"
    assert after["spendable"]["money_class"] == "VR_CASH"
    assert after["in_deficit"] is False


def test_the_days_spend_and_tokens_at_a_moment(books):
    budget(books, "15", "2026-09-01T00:00:00+00:00")
    aris = an_agent(books)
    # the day before, in Bucharest: 12.09 opens at 2026-09-11T21:00Z
    cost(books, "3", "2026-09-11T20:30:00+00:00")
    cost(books, "0.02", "2026-09-12T20:50:00+00:00")
    cost(books, "0.104", "2026-09-12T20:52:00+00:00")
    run(books, aris, "2026-09-12T20:48:10+00:00", "2026-09-12T20:48:40+00:00", tokens=(900, 100))
    # still running at 20:49: its tokens are not the day's yet
    run(books, aris, "2026-09-12T20:48:50+00:00", "2026-09-12T20:51:00+00:00", tokens=(400, 100))
    at_49 = reading(books, "2026-09-12T20:49:00+00:00")["budget"]
    at_53 = reading(books, "2026-09-12T20:53:00+00:00")["budget"]
    assert at_49["today"]["prompt_tokens"] + at_49["today"]["completion_tokens"] == 1000
    assert at_49["today"]["spent_usd"] == "0"
    assert at_53["today"]["prompt_tokens"] + at_53["today"]["completion_tokens"] == 1500
    assert at_53["today"]["spent_usd"] == "0.124"
    daily = at_53["budgets"][0]
    assert daily["period"] == "DAILY"
    assert daily["limit_usd"] == "15"
    assert daily["spent_usd"] == "0.124"
    assert daily["state"] == "OK"
    # after the studio's midnight the day is a new one
    next_day = reading(books, "2026-09-12T21:30:00+00:00")["budget"]
    assert next_day["today"]["spent_usd"] == "0"
    assert next_day["today"]["prompt_tokens"] == 0


def test_the_budget_is_the_one_that_was_active_then(books):
    budget(books, "15", "2026-09-01T00:00:00+00:00")
    with Session(books) as session, session.begin():
        session.execute(
            update(SpendingBudget).values(active=False, replaced_at="2026-09-20T00:00:00+00:00")
        )
    assert reading(books, "2026-08-31T00:00:00+00:00")["budget"]["budgets"] == []
    assert [
        b["limit_usd"] for b in reading(books, "2026-09-12T20:50:00+00:00")["budget"]["budgets"]
    ] == ["15"]
    assert reading(books, "2026-09-21T00:00:00+00:00")["budget"]["budgets"] == []


def test_an_estimate_counts_until_the_invoice_replaced_it(books):
    budget(books, "15", "2026-09-01T00:00:00+00:00")
    estimate = cost(books, "4.2", "2026-09-12T20:50:00+00:00")
    with Session(books) as session, session.begin():
        row = session.get(ProviderCostRecord, estimate)
        assert row is not None
        row.reconciled_at = "2026-09-12T20:57:00+00:00"
    assert reading(books, "2026-09-12T20:55:00+00:00")["budget"]["today"]["spent_usd"] == "4.2"
    assert reading(books, "2026-09-12T20:58:00+00:00")["budget"]["today"]["spent_usd"] == "0"


def test_a_hold_counts_while_it_was_held(books):
    budget(books, "15", "2026-09-01T00:00:00+00:00")
    with Session(books) as session, session.begin():
        session.add(
            SpendReservation(
                id=str(uuid4()),
                purpose="film",
                correlation_id=str(uuid4()),
                usd_micros=1_300_000,
                status="SETTLED",
                reserved_at="2026-09-12T20:51:00+00:00",
                released_at="2026-09-12T20:58:00+00:00",
            )
        )
    held = reading(books, "2026-09-12T20:55:00+00:00")["budget"]["budgets"][0]
    free = reading(books, "2026-09-12T20:59:00+00:00")["budget"]["budgets"][0]
    assert held["reserved_usd"] == "1.3"
    assert free["reserved_usd"] == "0"


def test_a_reading_now_is_what_the_live_books_say(books):
    budget(books, "15", "2026-09-01T00:00:00+00:00")
    aris = an_agent(books)
    fund(books, "50", "2026-09-10T08:00:00+00:00")
    now = datetime.now(UTC)
    earlier = now.replace(microsecond=0).isoformat()
    cost(books, "0.5", earlier)
    run(books, aris, earlier, earlier, tokens=(10, 5), cost_vr="0.01")
    at = datetime.now(UTC).isoformat()
    as_of = reading(books, at)
    live_treasury = treasury_snapshot(books)
    live_budget = budget_status(books)
    assert as_of["treasury"]["spendable"]["amount"] == live_treasury["spendable"]["amount"]
    assert as_of["budget"]["today"]["spent_usd"] == live_budget["today"]["spent_usd"]
    assert as_of["budget"]["today"]["prompt_tokens"] == live_budget["today"]["prompt_tokens"]
    assert as_of["budget"]["budgets"][0]["spent_usd"] == live_budget["budgets"][0]["spent_usd"]


def test_many_moments_are_one_request_and_a_fixed_number_of_indexed_queries(books):
    budget(books, "15", "2026-09-01T00:00:00+00:00")
    aris = an_agent(books)
    fund(books, "50", "2026-09-10T08:00:00+00:00")
    for m in range(10):
        cost(books, "0.02", f"2026-09-12T20:5{m}:00+00:00")
        run(books, aris, f"2026-09-12T20:4{m}:00+00:00", f"2026-09-12T20:4{m}:30+00:00")
    statements: list[tuple[str, tuple]] = []

    def count(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append((statement, tuple(parameters)))

    def measured(moments: list[str]) -> dict:
        statements.clear()
        event.listen(books, "before_cursor_execute", count)
        try:
            return economy_as_of(books, moments)
        finally:
            event.remove(books, "before_cursor_execute", count)

    moments = [f"2026-09-12T20:{m:02d}:15+00:00" for m in range(40, 60)]
    answer = measured(moments[:2])
    few = list(statements)
    answer = measured(moments)
    assert [r["at"] for r in answer["readings"]] == moments
    assert len(statements) == len(few), "the queries do not grow with the moments asked"
    assert len(statements) <= 8, statements
    ledger = [(s, p) for s, p in statements if "ledger_transaction" in s]
    assert len(ledger) == 2 and all(
        "ix_ledger_transaction_posted" in query_plan(books, s, p) for s, p in ledger
    ), [query_plan(books, s, p) for s, p in ledger]
    for name, table in (
        ("ix_ledger_transaction_posted", "ledger_transaction"),
        ("ix_provider_cost_status", "provider_cost_record"),
        ("ix_agent_run_started", "agent_run"),
        ("ix_spend_reservation_status", "spend_reservation"),
    ):
        found = [(s, p) for s, p in statements if f"FROM {table}" in s]
        assert found, (table, statements)
        assert name in query_plan(books, *found[0]), (table, found[0][0])


def test_the_route_answers_many_moments_and_refuses_nonsense(client, headers, engine):
    seed_chart_of_accounts(engine)
    ok = client.get(
        "/api/v1/economy/as-of",
        params=[("at", "2026-09-12T20:50:00Z"), ("at", "2026-09-12T23:59:00+03:00")],
        headers=headers,
    )
    assert ok.status_code == 200
    body = ok.json()
    assert [r["at"] for r in body["readings"]] == [
        "2026-09-12T20:50:00+00:00",
        "2026-09-12T20:59:00+00:00",
    ]
    assert body["timezone"] == "Europe/Bucharest"
    assert client.get("/api/v1/economy/as-of", headers=headers).status_code == 422
    assert (
        client.get("/api/v1/economy/as-of", params={"at": "noon"}, headers=headers).status_code
        == 422
    )
    too_many = [("at", "2026-09-12T20:50:00Z")] * 241
    assert client.get("/api/v1/economy/as-of", params=too_many, headers=headers).status_code == 422
