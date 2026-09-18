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
from app.agents.director import file_stage_reports
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


def test_a_task_reads_as_a_sentence_in_the_history_and_keeps_its_prompt(engine, staffed):
    """What the Owner saw: five identical walls of prompt, no answer, no way to tell apart."""
    nadia = staffed["agents"]["Accountant"]
    registry, _ = registry_with(
        staffed,
        lambda prompt: json.dumps(
            {"summary": "Zi fără cheltuieli.", "recommendations": [], "holds": []},
            ensure_ascii=False,
        ),
    )
    reconcile_day(engine, registry, str(uuid4()))

    run = next(item for item in agent_timeline(engine, nadia.id) if item["kind"] == "run")
    assert run["asked"].startswith("Închid ziua:")
    assert "USD" in run["asked"] and len(run["asked"]) < 200
    # The engineered prompt is not lost — it is one click away, not the headline.
    assert run["prompt"] != run["asked"] and len(run["prompt"]) > len(run["asked"])
    assert run["answered"] and "Zi fără cheltuieli" in run["answered"]


def test_a_report_an_employee_filed_is_not_shown_again_as_its_own_memory(engine, staffed):
    """The message and the memory of it say the same sentence; the timeline shows it once."""
    vera = staffed["agents"]["Publisher"]
    file_stage_reports(
        engine, {"publish": {"status": "SKIPPED", "reason": "Niciun canal legat."}}, str(uuid4())
    )

    items = agent_timeline(engine, vera.id)
    assert [item["kind"] for item in items] == ["message"]
    with Session(engine) as session:
        # Dropped from the view, kept in the record: the next run still remembers it.
        remembered = session.scalars(
            select(MemoryRecord).where(MemoryRecord.agent_id == vera.id)
        ).all()
        assert len(remembered) == 1


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
    assert first == {
        "render_job_id": job_id,
        "recorded": 2,
        "unpriced_scenes": 1,
        # No price moved here, so the Owner is not written to: an alert is a change of
        # price past the Owner's threshold, not a report of every render.
        "price_alerts": [],
    }
    assert record_render_costs(engine, job_id)["recorded"] == 0, "a re-run charges nothing"
    with Session(engine) as session:
        rows = session.scalars(select(ProviderCostRecord)).all()
        assert sorted(r.usd_micros for r in rows) == [150_000, 300_000]
        assert all(r.status == "ESTIMATED" and r.provider == "elevenlabs" for r in rows)
        assert session.get(Integration, identifier) is not None
    assert budget_status(engine, datetime.now(UTC))["today"]["spent_usd"] == "0.45"


# --------------------------------------------------------------------------- the business date


def _recorded_at(engine, reference: str, stamp: str) -> None:
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(ProviderCostRecord).where(ProviderCostRecord.external_reference == reference)
        )
        row.recorded_at = stamp


def test_a_budget_period_starts_at_the_studios_own_midnight_not_utcs(engine):
    """Bucharest is two hours ahead of UTC in September, three in December.

    A cost at 22:30 UTC on the 17th is 01:30 on the 18th where the studio is: today's, not
    yesterday's. The window used to open at UTC midnight, so the day's first two hours of
    spend were counted against the day before.
    """
    from zoneinfo import ZoneInfo

    from app.models import Studio

    with Session(engine) as session:
        assert session.get(Studio, 1).timezone == "Europe/Bucharest"
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="10"))
    set_budget(engine, BudgetCommand(period="MONTHLY", limit_usd="100"))
    record_provider_cost(
        engine, provider="runway", external_reference="late", status="ESTIMATED", amount="7.50"
    )
    record_provider_cost(
        engine, provider="runway", external_reference="earlier", status="ESTIMATED", amount="1.00"
    )
    _recorded_at(engine, "late", "2026-09-17T22:30:00+00:00")  # 01:30 local, the 18th
    _recorded_at(engine, "earlier", "2026-09-17T20:30:00+00:00")  # 23:30 local, the 17th

    now = datetime(2026, 9, 18, 0, 30, tzinfo=UTC)  # 03:30 in Bucharest
    status = budget_status(engine, now)
    daily = next(b for b in status["budgets"] if b["period"] == "DAILY")
    assert daily["spent_usd"] == "7.5", "the 01:30 local cost is today's; the 23:30 one is not"
    assert status["today"]["since"] == datetime(2026, 9, 17, 21, tzinfo=UTC).isoformat()
    assert not may_spend(engine, 3_000_000, now)["allowed"]
    assert may_spend(engine, 2_000_000, now)["allowed"]

    # The month too: 30 September 21:30 UTC is 1 October 00:30 in Bucharest.
    _recorded_at(engine, "late", "2026-09-30T21:30:00+00:00")
    _recorded_at(engine, "earlier", "2026-09-30T20:30:00+00:00")
    october = datetime(2026, 10, 1, 5, 0, tzinfo=UTC)
    monthly = next(b for b in budget_status(engine, october)["budgets"] if b["period"] == "MONTHLY")
    assert monthly["spent_usd"] == "7.5"
    assert budget_status(engine, october)["month"]["since"] == (
        datetime(2026, 10, 1, tzinfo=ZoneInfo("Europe/Bucharest")).astimezone(UTC).isoformat()
    )


# --------------------------------------------------------------------------- the letters


def test_a_day_without_a_film_is_never_silent_and_is_said_once(engine, staffed):
    from app.economy.accountant import budget_refusal_letter

    nadia = staffed["agents"]["Accountant"]
    first = budget_refusal_letter(
        engine, "Bugetul daily de 15 USD ar fi depășit: 14.99 USD cheltuiți deja.", str(uuid4())
    )
    assert first["written"] is True and first["message_id"]
    second = budget_refusal_letter(engine, "the same day, another reason", str(uuid4()))
    assert second["written"] is False and second["message_id"] == first["message_id"]
    with Session(engine) as session:
        letters = session.scalars(
            select(AgentMessage).where(AgentMessage.from_agent_id == nadia.id)
        ).all()
        assert len(letters) == 1
        letter = letters[0]
        assert letter.intent == "ESCALATE" and letter.body_json["to"] == "Owner"
        assert letter.body_json["kind"] == "budget_refusal"
        assert letter.body_json["date"] == first["date"]
        assert "14.99" in (letter.body_text or "")
        assert "nu a fost filmat" in (letter.body_text or "").lower()


def test_the_owner_is_told_once_a_day_what_waits_for_his_answer(engine, staffed):
    """Measured before this: a SUPERVISED day wrote one `owner_approval_request` per film and
    nothing else — the questions existed only for whoever opened the page that day."""
    from datetime import timedelta

    from app.economy.accountant import waiting_approvals_letter
    from app.services import request_approval

    nadia = staffed["agents"]["Accountant"]
    soon = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    later = (datetime.now(UTC) + timedelta(hours=20)).isoformat()
    with Session(engine) as session, session.begin():
        first = request_approval(
            session,
            "publishing.public_publish",
            "T3",
            "publisher",
            subject="asset-1",
            evidence="Cum se naște o stea → AMN Shorts (public)",
            cost_usd=4.2,
        )
        second = request_approval(
            session,
            "media.paid_generation_over_threshold",
            "T3",
            "director",
            subject="storyboard-2",
            evidence="storyboard 2, model fără preț",
            cost_usd=None,
        )
        first.expires_at, second.expires_at = soon, later
        asked = [first.id, second.id]

    written = waiting_approvals_letter(engine, str(uuid4()))
    assert written["written"] is True and written["questions"] == 2
    again = waiting_approvals_letter(engine, str(uuid4()))
    assert again["written"] is False and again["message_id"] == written["message_id"], (
        "one letter a day, whatever the number of questions"
    )

    with Session(engine) as session:
        letters = [
            m
            for m in session.scalars(select(AgentMessage))
            if m.body_json.get("kind") == "owner_waiting"
        ]
        assert len(letters) == 1
        letter = letters[0]
        assert letter.from_agent_id == nadia.id and letter.body_json["to"] == "Owner"
        assert letter.intent == "ESCALATE" and letter.body_json["owner_attention"] is True
        assert [q["id"] for q in letter.body_json["questions"]] == asked, "oldest first"
        assert letter.body_json["oldest_expires_at"] == soon
        text = letter.body_text or ""
        assert "2 întrebări" in text
        # Each question by what it is about, in his language, and what it would cost.
        assert "Publicarea unui film pe canalul lui" in text
        assert "Un randat plătit peste pragul stabilit" in text
        assert "4.2 USD" in text
        assert "necunoscut" in text, "a cost the studio cannot compute is never shown as zero"


def test_nothing_waits_and_the_accountant_writes_nothing(engine, staffed):
    from app.economy.accountant import waiting_approvals_letter
    from app.services import request_approval

    quiet = waiting_approvals_letter(engine, str(uuid4()))
    assert quiet == {"written": False, "message_id": None, "questions": 0}

    # A question he has already answered, and one the clock has passed, wait for nobody.
    with Session(engine) as session, session.begin():
        answered = request_approval(
            session, "publishing.public_publish", "T3", "publisher", subject="asset-9"
        )
        answered.result = "APPROVED"
        stale = request_approval(
            session, "research.fetch_page", "T2", "researcher", subject="host-9"
        )
        stale.expires_at = "2020-01-01T00:00:00+00:00"
    assert waiting_approvals_letter(engine, str(uuid4()))["questions"] == 0
    with Session(engine) as session:
        assert session.scalars(select(AgentMessage)).all() == []


def test_the_close_of_the_day_carries_the_letter_about_what_waits(engine, staffed):
    from app.economy.accountant import reconcile_day
    from app.services import request_approval

    with Session(engine) as session, session.begin():
        request_approval(
            session,
            "publishing.public_publish",
            "T3",
            "publisher",
            subject="asset-3",
            cost_usd=None,
        )
    registry, _ = registry_with(
        staffed,
        lambda prompt: json.dumps(
            {"summary": "Zi fără cheltuieli.", "recommendations": [], "holds": []},
            ensure_ascii=False,
        ),
    )
    reconcile_day(engine, registry, str(uuid4()))
    with Session(engine) as session:
        waiting = [
            m
            for m in session.scalars(select(AgentMessage))
            if m.body_json.get("kind") == "owner_waiting"
        ]
    assert len(waiting) == 1 and waiting[0].body_json["questions"][0]["cost_label"] == "necunoscut"


def test_the_token_ceiling_blocks_a_run_and_the_accountant_writes_once_a_day(engine, staffed):
    from types import SimpleNamespace

    from app.agents.models import AgentRun
    from app.economy.accountant import may_run_agent

    director = staffed["agents"]["Director"]

    def spent(prompt: int, completion: int) -> None:
        with Session(engine) as session, session.begin():
            session.add(
                AgentRun(
                    id=str(uuid4()),
                    agent_id=director.id,
                    task_type="mail_round",
                    objective="x",
                    prompt_template_version="t",
                    model_name="m",
                    provider_name="p",
                    status="SUCCEEDED",
                    prompt_tokens=prompt,
                    completion_tokens=completion,
                    cost_vr=None,
                    correlation_id=str(uuid4()),
                    started_at=utc_now(),
                    finished_at=utc_now(),
                )
            )

    unlimited = SimpleNamespace(agent_daily_token_budget=0)
    ceiling = SimpleNamespace(agent_daily_token_budget=100)
    spent(50, 30)
    assert may_run_agent(engine, unlimited)["allowed"], "zero is unlimited, as configured today"
    verdict = may_run_agent(engine, ceiling)
    assert verdict["allowed"] and verdict["tokens_used"] == 80 and verdict["ceiling"] == 100
    spent(15, 10)
    blocked = may_run_agent(engine, ceiling)
    assert blocked["allowed"] is False and blocked["status"] == "BLOCKED_BUDGET"
    assert "tokeni" in blocked["reason"] and "105" in blocked["reason"]
    assert blocked["letter"]["written"] is True
    again = may_run_agent(engine, ceiling)
    assert again["letter"]["written"] is False, "one letter a day, however many runs are refused"
    with Session(engine) as session:
        letters = [
            m
            for m in session.scalars(select(AgentMessage))
            if m.body_json.get("kind") == "token_ceiling"
        ]
        assert len(letters) == 1 and letters[0].body_json["to"] == "Owner"
        assert letters[0].from_agent_id == staffed["agents"]["Accountant"].id


# --------------------------------------------------------------------------- failed renders


def test_a_render_the_vendor_may_have_charged_for_is_costed_even_though_it_failed(
    engine, tmp_path, elevenlabs_api, client, headers
):
    from app.economy.accountant import record_failed_render_cost
    from app.economy.services import list_provider_costs
    from app.integrations.models import ProviderResource

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
            select(ProviderResource).where(ProviderResource.remote_id == model_id)
        )
        resource.pricing = {"per_1k_characters_usd": 0.30}
    storyboard_id = make_storyboard(engine, tmp_path)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="10"))
    job_id = str(uuid4())
    scenes = [
        {"scene_index": 1, "model_id": model_id, "characters": 1000},
        {"scene_index": 2, "model_id": model_id, "characters": 500},
    ]
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "media.render_failed", "video_render_job", job_id, 1, {}, str(uuid4())
        )
        # The assembler marks a failed job without its production record, as it does today.
        session.add(
            VideoRenderJob(
                id=job_id,
                storyboard_id=storyboard_id,
                status="FAILED",
                started_at=utc_now(),
                finished_at=utc_now(),
                production_json={},
                event_id=event.event_id,
            )
        )

    nothing = record_failed_render_cost(engine, job_id)
    assert nothing == {"render_job_id": job_id, "recorded": 0, "unpriced_scenes": 0, "scenes": 0}

    outcome = record_failed_render_cost(
        engine,
        job_id,
        scenes_attempted=scenes,
        voice_integration_id=identifier,
        correlation_id=str(uuid4()),
    )
    assert (outcome["recorded"], outcome["scenes"]) == (2, 2)
    repeat = record_failed_render_cost(
        engine, job_id, scenes_attempted=scenes, voice_integration_id=identifier
    )
    assert repeat["recorded"] == 0, "a re-run charges nothing"
    with Session(engine) as session:
        rows = session.scalars(select(ProviderCostRecord)).all()
        assert sorted(r.usd_micros for r in rows) == [150_000, 300_000]
        assert all(r.failed and r.status == "ESTIMATED" for r in rows)
        assert all(":failed:" in r.external_reference for r in rows)
        assert all(r.attribution_json["failed"] is True for r in rows)
    assert budget_status(engine)["budgets"][0]["spent_usd"] == "0.45", "counted like any estimate"
    costs = list_provider_costs(engine)
    assert all(c["failed"] is True and c["label"] == "ESTIMAT (randare eșuată)" for c in costs)


# --------------------------------------------------------------------------- motion bought or not

#: The shapes `media.assembler.assemble_video_job` writes into a scene's `motion` entry, one
#: per branch of its motion loop, with the fields that branch sets. The rehearsal of
#: 2026-09-18 on a copy of the Owner's studio wrote four ESTIMATED Runway rows (0.204 +
#: 0.306 + 0.372 + 0.558 = 1.44 USD) for the "unreachable" shape and settled both films'
#: holds against them: the books charged shots that never existed.
_SHOT = {
    "provider": "RUNWAY",
    "model": "a-motion",
    "asked_seconds": 10.2,
    "tier": "HERO",
    "scene_category": "GENERAL",
    "decision": None,
}
MOTION_SHAPES: dict[str, tuple[dict | None, str | None]] = {
    # Bought, and the vendor named the credits (assembler :1240-1251).
    "bought_with_credits": (
        {**_SHOT, "quoted_credits": 20.0, "estimated_credits": 20.0, "bytes": 4096, "task": "OK"},
        "200000",
    ),
    # Bought from a vendor that named no credits: the catalogue's price a second decides.
    "bought_without_credits": ({**_SHOT, "bytes": 4096, "task": "SUCCEEDED"}, "204000"),
    # Generated and charged, then lost on the way home (assembler :1253-1265).
    "paid_but_lost": (
        {
            **_SHOT,
            "refused": "the clip could not be downloaded",
            "estimated_credits": 20.0,
            "paid_but_lost": True,
        },
        "200000",
    ),
    # The vendor could not be reached or refused the task, and charged nothing (:1254).
    "refused_by_the_vendor": (
        {**_SHOT, "refused": "api.dev.runwayml.com could not be reached (after 3 attempts)"},
        None,
    ),
    # The studio's own price gate refused the quote before buying (:1197-1225).
    "refused_by_the_price_gate": (
        {
            **_SHOT,
            "quoted_credits": 90.0,
            "quoted_usd": 0.9,
            "price_was_stale": {"stored": 0.02, "observed": 0.0882},
            "refused": "the vendor quotes 0.90 USD, above the 0.60 USD this render may spend "
            "on a shot",
        },
        None,
    ),
    # Never asked for: a test's scene limit, a spent budget, no model (:1120-1149). The
    # scene is a still given a push, and only the still is bought.
    "fell_back_to_a_still": (None, None),
}


def _a_runway_connection(engine) -> str:
    from app.integrations.models import Integration, ProviderResource

    integration_id = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "settings.integration_saved", "integration", integration_id, 1, {}, "c"
        )
        session.add(
            Integration(
                id=integration_id,
                kind="runway",
                name="runway",
                # One dollar, a hundred credits: the Owner's own purchase.
                config={"credit_usd": "0.01"},
                encrypted_secrets=vault_for(engine).encrypt({"api_key": "k"}),
                secret_fields=["api_key"],
                version=1,
                status="VERIFIED",
                checked_at=utc_now(),
                event_id=event.event_id,
            )
        )
        session.flush()
        for remote_id, pricing in (
            ("a-still", {"per_image_usd": 0.02}),
            ("a-motion", {"per_second_usd": 0.02}),
        ):
            session.add(
                ProviderResource(
                    id=str(uuid4()),
                    integration_id=integration_id,
                    resource_type="MODEL",
                    remote_id=remote_id,
                    name=remote_id,
                    api_metadata={},
                    api_available=True,
                    last_seen_at=utc_now(),
                    pricing=pricing,
                    capabilities={},
                    metadata_version=1,
                )
            )
    return integration_id


def _a_render_with_one_shot(engine, tmp_path, shape: dict | None, status: str) -> tuple[str, str]:
    integration_id = _a_runway_connection(engine)
    scene: dict = {"scene_index": 1, "model_id": "unpriced-voice", "characters": 0}
    if shape is not None:
        scene["motion"] = {**shape, "integration_id": integration_id}
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
                status=status,
                started_at=utc_now(),
                finished_at=utc_now(),
                production_json={
                    "image": {"integration_id": integration_id, "model": "a-still"},
                    "scenes": [scene],
                },
                event_id=event.event_id,
            )
        )
    return job_id, integration_id


def _charged(engine) -> dict[str, int]:
    with Session(engine) as session:
        return {
            row.attribution_json["unit"]: row.usd_micros
            for row in session.scalars(select(ProviderCostRecord))
        }


@pytest.mark.parametrize("shape_name", list(MOTION_SHAPES))
def test_a_finished_render_charges_a_shot_only_when_it_was_bought(engine, tmp_path, shape_name):
    shape, motion_micros = MOTION_SHAPES[shape_name]
    job_id, _ = _a_render_with_one_shot(engine, tmp_path, shape, "COMPLETED")

    record_render_costs(engine, job_id)

    charged = _charged(engine)
    # The still was bought in every shape: a refused shot falls back to it.
    assert charged.pop("image") == 20_000
    if motion_micros is None:
        assert charged == {}, f"{shape_name}: a shot nobody paid for was charged"
    else:
        assert charged == {"motion": int(motion_micros)}, shape_name


@pytest.mark.parametrize("shape_name", list(MOTION_SHAPES))
def test_a_failed_render_charges_a_shot_by_the_same_rule(engine, tmp_path, shape_name):
    from app.economy.accountant import record_failed_render_cost

    shape, motion_micros = MOTION_SHAPES[shape_name]
    job_id, _ = _a_render_with_one_shot(engine, tmp_path, shape, "FAILED")

    record_failed_render_cost(engine, job_id)

    charged = _charged(engine)
    assert charged.pop("image") == 20_000
    if motion_micros is None:
        assert charged == {}, f"{shape_name}: a lost render charged a shot never bought"
    else:
        assert charged == {"motion": int(motion_micros)}, shape_name


def test_a_refused_shot_teaches_the_studio_no_price(engine, tmp_path):
    """A price is learnt from what a render was charged; a shot that was refused was charged
    nothing, and its seconds must not dilute the price a second of the bought one teaches."""
    from app.integrations.models import ProviderResource

    job_id, integration_id = _a_render_with_one_shot(
        engine, tmp_path, MOTION_SHAPES["refused_by_the_price_gate"][0], "COMPLETED"
    )
    record_render_costs(engine, job_id)
    with Session(engine) as session:
        row = session.scalar(
            select(ProviderResource).where(
                ProviderResource.integration_id == integration_id,
                ProviderResource.remote_id == "a-motion",
            )
        )
        assert row.pricing == {"per_second_usd": 0.02}, "a refused quote rewrote the price"
