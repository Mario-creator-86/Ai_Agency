"""The books are kept by someone, the Owner can talk to anyone, and nothing is said unread.

Local tests with a scripted model; nothing here reaches a vendor. What is asserted: an
employee's timeline is its own audit trail read back; a chat is an ordinary run through its
identity; the Accountant exists, sits in the accounting office, and closes the day from the
books; a budget refuses a render it cannot afford and escalates when crossed; and a render's
narration is costed at the stored price of the model that voiced it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from app.agents.history import agent_timeline, chat
from app.agents.messages import post_message
from app.agents.models import Agent, AgentMessage, MemoryRecord, ModelRecord, Role
from app.agents.services import seed_initial_workforce, seed_missing_workforce
from app.economy.accountant import (
    AccountantError,
    NoAccountant,
    reconcile_day,
    record_render_costs,
)
from app.economy.budget import BudgetCommand, budget_status, may_spend, set_budget
from app.economy.models import ProviderCostRecord
from app.economy.services import record_provider_cost
from app.integrations.vault import CredentialVault
from app.media.models import CharacterBible, VideoRenderJob
from app.media.services import seed_default_character_bibles
from app.models import OwnerPolicy
from app.office.services import get_office_layout_with_assignments
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.runbook.stages import _post_run
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_production_policy import make_storyboard

# --------------------------------------------------------------------------- helpers


class ScriptedModel:
    def __init__(self, answer):
        self.answer = answer
        self.calls: list[dict] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        self.calls.append({"prompt": prompt, "system": kwargs.get("system")})
        return GenerateResult(self.answer(prompt), 10, 40, None)


@pytest.fixture
def staffed(engine):
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        agents = {
            role.name: agent
            for agent, role in session.execute(
                select(Agent, Role).join(Role, Agent.role_id == Role.id)
            ).all()
        }
        provider_id = next(iter(agents.values())).provider_id
        session.expunge_all()
    return {"agents": agents, "provider_id": provider_id}


def registry_with(staffed, answer):
    registry = ProviderRegistry()
    model = ScriptedModel(answer)
    registry.register(staffed["provider_id"], model)
    return registry, model


def vault_for(engine):
    return CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))


# --------------------------------------------------------------------------- history and chat


def test_the_owner_can_talk_to_an_employee_and_the_exchange_is_in_its_history(
    client, headers, engine, staffed
):
    sarah = staffed["agents"]["Director"]
    registry, model = registry_with(
        staffed, lambda prompt: "Am ales tema cu cele mai multe dovezi; motivul este în registru."
    )
    answer = chat(engine, registry, sarah.id, "Ce ai decis azi și de ce?", str(uuid4()))
    assert answer["kind"] == "run" and answer["task_type"] == "owner_chat"
    assert answer["asked"] == "Ce ai decis azi și de ce?"
    assert "cele mai multe dovezi" in answer["answered"]
    # The question travels as data inside the prompt; the identity is the system prompt.
    assert "owner-question" in model.calls[-1]["prompt"]
    assert model.calls[-1]["system"].startswith("You are Sarah (Director)")

    with Session(engine) as session, session.begin():
        post_message(
            session,
            intent="STATUS",
            subject="publish: COMPLETED — 1 video",
            body={"stage": "publish"},
            from_agent_id=staffed["agents"]["Publisher"].id,
        )
        session.add(
            MemoryRecord(
                id=str(uuid4()),
                agent_id=sarah.id,
                memory_class="AGENT_OPINION",
                content="Chose today's topic: more verified claims.",
                source_type="run",
                source_id=answer["id"],
                created_at=utc_now(),
            )
        )
    timeline = agent_timeline(engine, sarah.id)
    kinds = [item["kind"] for item in timeline]
    assert "run" in kinds and "memory" in kinds
    assert not any(item["kind"] == "message" for item in timeline), "another employee's report"
    run_item = next(item for item in timeline if item["kind"] == "run")
    assert (
        run_item["asked"].endswith("Ce ai decis azi și de ce?")
        or "owner-question" in run_item["asked"]
    )
    assert run_item["answered"].startswith("Am ales tema")

    listed = client.get(f"/api/v1/agents/{sarah.id}/history", headers=headers).json()["timeline"]
    assert len(listed) == len(timeline)
    # Through the API the app has no model registered, so the chat says so instead of pretending.
    refused = client.post(
        f"/api/v1/agents/{sarah.id}/chat", headers=headers, json={"message": "Salut"}
    )
    assert refused.status_code == 200 and refused.json()["status"] != "SUCCEEDED"


# --------------------------------------------------------------------------- the accountant


def test_the_accountant_is_hired_into_an_existing_studio_with_a_bible_and_a_desk(engine):
    """The seed adds Nadia to a studio that already has its seven employees, once."""
    seed_initial_workforce(engine)
    with Session(engine) as session:
        roles = {r.name: r for r in session.scalars(select(Role))}
        assert "Accountant" in roles
        agent = session.scalar(select(Agent).where(Agent.role_id == roles["Accountant"].id))
        assert agent is not None and agent.display_name == "Nadia (Accountant)"
        assert roles["Accountant"].work_contract_json["reports_to"] == "Director"
        assert "reconcile_costs" in roles["Accountant"].allowed_task_types
    assert seed_missing_workforce(engine) == [], "hiring is idempotent"
    seed_default_character_bibles(engine)
    with Session(engine) as session:
        bible = session.scalar(
            select(CharacterBible).where(CharacterBible.canonical_name == "Nadia Accountant")
        )
        assert bible is not None and bible.employee_id == agent.id
        assert bible.speech_style_json["register"] == "bookkeeping report"
    layout = get_office_layout_with_assignments(engine)
    finance = next(z for z in layout["zones"] if z["zone_type"] == "FINANCE")
    assert finance["name"] == "Ground Floor — Accounting & Treasury"
    assert not any(z["zone_type"] == "LOUNGE" for z in layout["zones"])
    seated = [a for a in layout["assignments"] if a["display_name"] == "Nadia (Accountant)"]
    assert seated and seated[0]["desk_id"] == "desk_accounting"


def test_a_studio_hired_before_the_accountant_existed_gets_one_on_the_directors_model(engine):
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        roles = {r.name: r for r in session.scalars(select(Role))}
        nadia = session.scalar(select(Agent).where(Agent.role_id == roles["Accountant"].id))
        session.delete(nadia)
        # The role goes too, so the hire has to create it from the seed's definition.
        from app.agents.models import RoleCapability

        for link in session.scalars(
            select(RoleCapability).where(RoleCapability.role_id == roles["Accountant"].id)
        ):
            session.delete(link)
        # No ORM relationship ties Agent to Role, so the deletes are ordered by hand.
        session.flush()
        session.delete(roles["Accountant"])
    assert seed_missing_workforce(engine) == ["Nadia (Accountant)"]
    with Session(engine) as session:
        roles = {r.name: r for r in session.scalars(select(Role))}
        nadia = session.scalar(select(Agent).where(Agent.role_id == roles["Accountant"].id))
        director = session.scalar(select(Agent).where(Agent.role_id == roles["Director"].id))
        assert nadia.provider_id == director.provider_id and nadia.lifecycle == "ACTIVE"


# --------------------------------------------------------------------------- budget


def test_a_budget_is_measured_from_the_books_and_refuses_what_it_cannot_afford(
    client, headers, engine, staffed
):
    from app.economy.services import seed_chart_of_accounts

    seed_chart_of_accounts(engine)
    assert may_spend(engine, 10_000_000)["allowed"], "with no budget nothing is refused"
    saved = client.put(
        "/api/v1/economy/budget",
        headers=headers,
        json={"period": "DAILY", "limit_usd": "10"},
    )
    assert saved.status_code == 200 and saved.json()["limit_usd"] == "10"
    record_provider_cost(
        engine, provider="elevenlabs", external_reference="inv-1", status="ESTIMATED", amount="7.50"
    )
    status = budget_status(engine)
    daily = status["budgets"][0]
    assert (daily["spent_usd"], daily["remaining_usd"], daily["state"]) == ("7.5", "2.5", "OK")
    assert may_spend(engine, 2_000_000)["allowed"]
    refused = may_spend(engine, 3_000_000)
    assert not refused["allowed"] and "ar fi depășit" in refused["reason"]
    record_provider_cost(
        engine, provider="elevenlabs", external_reference="inv-2", status="BILLED", amount="1.00"
    )
    assert budget_status(engine)["budgets"][0]["state"] == "WARNING"
    assert budget_status(engine)["today"]["by_provider"][0]["billed_usd_micros"] == 1_000_000
    # A new limit replaces the old one and keeps it; "0" retires it.
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="5"))
    assert budget_status(engine)["budgets"][0]["state"] == "EXCEEDED"
    assert not may_spend(engine, 0)["allowed"], "an exceeded budget refuses even the unpriced"
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="0"))
    assert budget_status(engine)["budgets"] == []
    view = client.get("/api/v1/economy/budget", headers=headers).json()
    assert view["today"]["spent_usd"] == "8.5"


def test_the_accountant_closes_the_day_from_the_books_and_an_exceeded_budget_escalates(
    engine, staffed
):
    nadia = staffed["agents"]["Accountant"]
    set_budget(engine, BudgetCommand(period="MONTHLY", limit_usd="5"))
    record_provider_cost(
        engine, provider="runway", external_reference="task-9", status="ESTIMATED", amount="6.25"
    )
    seen: dict = {}

    def answer(prompt):
        seen["prompt"] = prompt
        return json.dumps(
            {
                "summary": "Luna a depășit limita cu 1.25 USD; toată cheltuiala este la Runway.",
                "recommendations": [
                    "Ridică limita sau oprește randările video până la 1 octombrie."
                ],
                "holds": ["video"],
                "continue_spending": False,
            }
        )

    registry, model = registry_with(staffed, answer)
    close = reconcile_day(engine, registry, str(uuid4()))
    assert close["intent"] == "ESCALATE" and "6.25" in close["headline"]
    assert model.calls[-1]["system"].startswith("You are Nadia (Accountant), Accountant")
    # The figures the model was given are the books', not its own.
    assert '"spent_usd": "6.25"' in seen["prompt"] and '"state": "EXCEEDED"' in seen["prompt"]
    with Session(engine) as session:
        message = session.get(AgentMessage, close["message_id"])
        assert message.from_agent_id == nadia.id and message.to_agent_id is None
        assert message.body_json["owner_attention"] is True
        assert message.body_json["holds"] == ["video"]
        assert message.body_json["figures"]["budgets"][0]["state"] == "EXCEEDED"
        classes = {
            m.memory_class
            for m in session.scalars(select(MemoryRecord).where(MemoryRecord.agent_id == nadia.id))
        }
        assert {"AGENT_OPINION", "HISTORICAL_EVENT", "TEMP_CONTEXT"} <= classes

    # Prose instead of the schema keeps the figures and refuses the report.
    registry, _ = registry_with(staffed, lambda prompt: "All good, I think.")
    with pytest.raises(AccountantError):
        reconcile_day(engine, registry, str(uuid4()))


def test_the_books_report_in_the_evening_inbox_is_filed_by_the_accountant(engine, staffed):
    """post_run turns the close into a stage report; it must carry Nadia's name, not Sarah's."""
    nadia, sarah = staffed["agents"]["Accountant"], staffed["agents"]["Director"]
    registry, _ = registry_with(
        staffed,
        lambda prompt: json.dumps(
            {"summary": "Zi fără cheltuieli.", "recommendations": [], "holds": []}
        ),
    )
    outcome = _post_run(engine, registry, {})
    assert outcome["artefacts"]["reports"] == 1
    with Session(engine) as session:
        report = session.scalar(
            select(AgentMessage)
            .where(AgentMessage.subject.like("books:%"))
            .order_by(AgentMessage.created_at.desc())
        )
        assert report is not None and report.from_agent_id == nadia.id
        assert report.from_agent_id != sarah.id
        assert report.subject.startswith("books: STATUS — Azi 0 USD")


def test_without_an_accountant_the_close_says_so(engine, staffed):
    with Session(engine) as session, session.begin():
        session.get(Agent, staffed["agents"]["Accountant"].id).lifecycle = "TERMINATED"
    registry, _ = registry_with(staffed, lambda prompt: "{}")
    with pytest.raises(NoAccountant):
        reconcile_day(engine, registry, str(uuid4()))


def test_a_render_is_costed_per_scene_at_the_stored_price_and_only_once(
    engine, tmp_path, staffed, elevenlabs_api, client, headers
):
    from app.integrations.models import Integration, ProviderResource

    identifier = str(uuid4())
    saved = client.put(
        f"/api/v1/settings/integrations/{identifier}",
        headers=headers,
        json={"kind": "elevenlabs", "name": "Voice", "secrets": {"api_key": f"k-{uuid4()}"}},
    )
    assert saved.status_code == 200
    model_id = elevenlabs_api.models[0]["model_id"]
    with Session(engine) as session, session.begin():
        resource = session.scalar(
            select(ProviderResource).where(
                ProviderResource.integration_id == identifier,
                ProviderResource.remote_id == model_id,
            )
        )
        resource.pricing = {"per_1k_characters_usd": 0.30}
    storyboard_id = make_storyboard(engine, tmp_path)
    job_id = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "media.render_started", "video_render_job", job_id, 1, {}, str(uuid4())
        )
        session.add(
            VideoRenderJob(
                id=job_id,
                storyboard_id=storyboard_id,
                status="COMPLETED",
                output_asset_id=None,
                started_at=utc_now(),
                finished_at=utc_now(),
                production_json={
                    "voice": {"integration_id": identifier},
                    "scenes": [
                        {"scene_index": 1, "model_id": model_id, "characters": 1000},
                        {"scene_index": 2, "model_id": model_id, "characters": 500},
                        {"scene_index": 3, "model_id": "unpriced-model", "characters": 400},
                    ],
                },
                event_id=event.event_id,
            )
        )
    first = record_render_costs(engine, job_id)
    assert first == {"render_job_id": job_id, "recorded": 2, "unpriced_scenes": 1}
    assert record_render_costs(engine, job_id)["recorded"] == 0, "a re-run charges nothing"
    with Session(engine) as session:
        rows = session.scalars(select(ProviderCostRecord)).all()
        assert sorted(r.usd_micros for r in rows) == [150_000, 300_000]
        assert all(r.status == "ESTIMATED" and r.provider == "elevenlabs" for r in rows)
        assert session.get(Integration, identifier) is not None
    assert budget_status(engine, datetime.now(UTC))["today"]["spent_usd"] == "0.45"
