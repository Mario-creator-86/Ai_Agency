"""An employee's model run is refused when a USD budget is already exceeded (MONEY-10).

`run_agent_task` asked only `may_run_agent`, a token ceiling whose default (0) means none, so
an EXCEEDED daily or monthly budget did not stop a single run, although `spend_since` counts
their `cost_vr`: measured on a live copy, 391 Ollama Cloud runs went through under no ceiling.
Now `may_run_agent` also reads the Owner's USD budgets: past one, the run is recorded
BLOCKED_BUDGET, the model is never asked, and the Accountant writes to the Owner once that day.

The model is faked at the provider boundary; no socket is opened.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.agents import services as agent_services
from app.agents.models import Agent, AgentMessage, AgentRun, ModelRecord
from app.agents.services import run_agent_task, seed_initial_workforce
from app.economy.accountant import may_run_agent
from app.economy.budget import BudgetCommand, set_budget
from app.economy.services import record_provider_cost
from app.models import OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from sqlalchemy import select
from sqlalchemy.orm import Session


class Model:
    """An employee's model, faked: counts every question it is asked."""

    def __init__(self) -> None:
        self.asked = 0

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        self.asked += 1
        return GenerateResult("un răspuns", 10, 10, None)


def a_running_studio(engine, monkeypatch) -> tuple[str, ProviderRegistry, Model]:
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        for record in session.scalars(select(ModelRecord)):
            record.is_available = True
    with Session(engine) as session:
        agent = session.scalars(select(Agent)).first()
        agent_id, provider_id = agent.id, agent.provider_id
    model = Model()
    registry = ProviderRegistry()
    registry.register(provider_id, model)
    # No token ceiling at all, as a fresh studio ships: only the USD budget can refuse.
    monkeypatch.setattr(
        agent_services, "_studio_settings", lambda: SimpleNamespace(agent_daily_token_budget=0)
    )
    return agent_id, registry, model


def spend(engine, usd: str) -> None:
    record_provider_cost(
        engine,
        provider="runway",
        external_reference=f"test:{uuid4()}",
        status="ESTIMATED",
        amount=usd,
        attribution={"step": "stills"},
        correlation_id=str(uuid4()),
    )


def test_an_exceeded_daily_budget_refuses_the_run_before_the_model_is_asked(engine, monkeypatch):
    agent_id, registry, model = a_running_studio(engine, monkeypatch)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="1"))
    spend(engine, "2.000000")

    blocked = run_agent_task(engine, registry, agent_id, "t", "spune ceva", "v1", str(uuid4()))

    assert blocked["status"] == "BLOCKED_BUDGET", blocked
    assert model.asked == 0, "the model was asked while the budget was exceeded"
    with Session(engine) as session:
        row = session.get(AgentRun, blocked["id"])
        assert row.status == "BLOCKED_BUDGET"
        assert "zilnic" in (row.error_detail or "")
        assert not row.prompt_tokens and not row.completion_tokens


def test_an_exceeded_monthly_budget_refuses_as_well(engine, monkeypatch):
    agent_id, registry, model = a_running_studio(engine, monkeypatch)
    set_budget(engine, BudgetCommand(period="MONTHLY", limit_usd="1"))
    spend(engine, "1.500000")

    blocked = run_agent_task(engine, registry, agent_id, "t", "spune ceva", "v1", str(uuid4()))

    assert blocked["status"] == "BLOCKED_BUDGET"
    assert model.asked == 0


def test_a_budget_that_still_has_room_lets_the_run_go(engine, monkeypatch):
    agent_id, registry, model = a_running_studio(engine, monkeypatch)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="5"))
    spend(engine, "2.000000")

    ran = run_agent_task(engine, registry, agent_id, "t", "spune ceva", "v1", str(uuid4()))

    assert ran["status"] == "SUCCEEDED", ran
    assert model.asked == 1


def test_the_owner_hears_about_it_once_a_day(engine):
    seed_initial_workforce(engine)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="1"))
    spend(engine, "2.000000")
    settings = SimpleNamespace(agent_daily_token_budget=0)

    first = may_run_agent(engine, settings)
    second = may_run_agent(engine, settings)

    assert first["allowed"] is False and second["allowed"] is False
    assert first["status"] == "BLOCKED_BUDGET"
    assert "Trezorerie → Buget și cheltuieli" in first["reason"]
    with Session(engine) as session:
        letters = [
            row
            for row in session.scalars(
                select(AgentMessage).where(AgentMessage.to_agent_id.is_(None))
            )
            if (row.body_json or {}).get("kind") == "budget_exceeded_agents"
        ]
    assert len(letters) == 1


def test_the_accountants_close_still_runs_to_report_the_exceeded_budget(engine):
    """The daily close is how the Owner learns the budget is exceeded: it is not silenced."""
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="1"))
    spend(engine, "2.000000")
    settings = SimpleNamespace(agent_daily_token_budget=0)

    assert may_run_agent(engine, settings, task_type="reconcile_day")["allowed"] is True
    assert may_run_agent(engine, settings, task_type="script_draft")["allowed"] is False


def test_the_preflight_says_when_a_paid_model_runs_with_no_token_ceiling(engine):
    from app.agents.models import ProviderRecord
    from app.runbook.preflight import DEGRADING, _token_ceiling_check

    seed_initial_workforce(engine)
    with Session(engine) as session:
        local = _token_ceiling_check(session, SimpleNamespace(agent_daily_token_budget=0))
    # The seeded workforce thinks on a local model with no price: nothing to warn about.
    assert local["ok"] is True

    with Session(engine) as session, session.begin():
        for provider in session.scalars(select(ProviderRecord)):
            provider.provider_type = "openai"
    with Session(engine) as session:
        none = _token_ceiling_check(session, SimpleNamespace(agent_daily_token_budget=0))
        set_ = _token_ceiling_check(session, SimpleNamespace(agent_daily_token_budget=50_000))

    assert none["ok"] is False and none["severity"] == DEGRADING
    assert none["code"] == "agent_token_ceiling.none"
    assert "openai" in none["message"] and "plafon zilnic de tokeni" in none["message"]
    assert none["technical"]["settings"] == ["STUDIO_AGENT_DAILY_TOKEN_BUDGET"]
    assert set_["ok"] is True
