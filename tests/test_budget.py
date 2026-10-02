"""PAGE-05: the daily budget is never retired by an empty field.

Before: `<input id="budget-limit">` sent ``limit_usd: ''`` on Enter, `set_budget` read it as 0 and
retired the active budget, and the preflight then said nothing in the budget refused a film of
the day. Now an empty or zero limit is refused (422), retiring needs ``retire: true``, and the
command carries an id (a repeat changes nothing twice) and the version the page read.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.economy.budget import BudgetCommand, budget_status, set_budget
from app.economy.models import SpendingBudget
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

ROUTE = "/api/v1/economy/budget"


def active(engine, period: str = "DAILY") -> list[SpendingBudget]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(SpendingBudget).where(
                    SpendingBudget.period == period, SpendingBudget.active.is_(True)
                )
            )
        )


@pytest.mark.parametrize("limit", ["", "   ", "0", "0.00", "-1"])
def test_an_empty_or_zero_limit_is_refused_and_the_budget_stands(client, headers, engine, limit):
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="15"))
    answer = client.put(ROUTE, headers=headers, json={"period": "DAILY", "limit_usd": limit})
    assert answer.status_code == 422
    assert len(active(engine)) == 1, "the daily budget is still there"


def test_the_command_refuses_a_zero_limit_without_retire():
    with pytest.raises(ValidationError):
        BudgetCommand(period="DAILY", limit_usd="")
    with pytest.raises(ValidationError):
        BudgetCommand(period="DAILY", limit_usd="0")
    assert BudgetCommand(period="DAILY", retire=True).retire is True
    with pytest.raises(ValidationError):
        BudgetCommand(period="DAILY", limit_usd="15", retire=True)


def test_retiring_needs_retire_true(client, headers, engine):
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="15"))
    answer = client.put(ROUTE, headers=headers, json={"period": "DAILY", "retire": True})
    assert answer.status_code == 200, answer.text
    assert answer.json()["active"] is False
    assert active(engine) == []


def test_the_command_carries_an_id_and_a_repeat_changes_nothing_twice(client, headers, engine):
    command = {"period": "DAILY", "limit_usd": "15", "command_id": str(uuid4())}
    first = client.put(ROUTE, headers=headers, json=command)
    second = client.put(ROUTE, headers=headers, json=command)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    with Session(engine) as session:
        assert len(list(session.scalars(select(SpendingBudget)))) == 1
    other = client.put(ROUTE, headers=headers, json={**command, "limit_usd": "20"})
    assert other.status_code == 422
    assert "altă" in other.json()["detail"] or "alt" in other.json()["detail"]


def test_the_version_the_page_read_must_still_be_the_budgets(client, headers, engine):
    versions = budget_status(engine)["versions"]
    assert versions == {"DAILY": 0, "MONTHLY": 0}
    set_ok = client.put(
        ROUTE, headers=headers, json={"period": "DAILY", "limit_usd": "15", "expected_version": 0}
    )
    assert set_ok.status_code == 200
    assert budget_status(engine)["versions"]["DAILY"] == 1
    stale = client.put(
        ROUTE, headers=headers, json={"period": "DAILY", "limit_usd": "9", "expected_version": 0}
    )
    assert stale.status_code == 422
    assert "recitește" in stale.json()["detail"]
    assert active(engine)[0].limit_usd_micros == 15_000_000
    retired = client.put(
        ROUTE, headers=headers, json={"period": "DAILY", "retire": True, "expected_version": 1}
    )
    assert retired.status_code == 200
    assert budget_status(engine)["versions"]["DAILY"] == 2, "a retirement is a change too"
