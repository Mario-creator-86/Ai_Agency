"""Every employee knows who it is, remembers what the studio established, and reports.

Local tests with a scripted model; nothing here claims a real model answered. What is
asserted is the wiring: the identity the model is given comes from stored data, memory is
written by services on real outcomes and read by role scope, reports and escalations reach the
Director, and her decisions become messages and memory — never a change to a gate.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.agents.director import DirectorError, director_review, file_stage_reports
from app.agents.identity import compose_identity, seed_role_contracts
from app.agents.memory import recall, remember
from app.agents.messages import open_messages, post_message
from app.agents.models import Agent, AgentMessage, AgentRun, MemoryRecord, ModelRecord, Role
from app.agents.reviews import (
    ReviewError,
    approved_metadata,
    publication_hold,
    review_narration,
)
from app.agents.services import run_agent_task, seed_initial_workforce
from app.media.models import CharacterBible
from app.media.services import seed_default_character_bibles
from app.models import DomainEvent, OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.schemas import PolicyCommand
from app.services import change_stop
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_production_policy import make_storyboard

# --------------------------------------------------------------------------- helpers


class ScriptedModel:
    """Answers by what the prompt asks for; records the system prompt it was given."""

    def __init__(self, answer):
        self.answer = answer
        self.calls: list[dict] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        self.calls.append({"model": model, "prompt": prompt, "system": kwargs.get("system")})
        return GenerateResult(self.answer(prompt), 10, 40, None)


@pytest.fixture
def staffed(engine):
    """The seeded studio: roles with contracts, agents, bibles linked, models available."""
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


# --------------------------------------------------------------------------- identity


def test_every_employee_is_told_who_it_is_from_stored_data(engine, staffed):
    with Session(engine) as session:
        for role_name, agent in staffed["agents"].items():
            row = session.get(Agent, agent.id)
            role = session.get(Role, row.role_id)
            assert role.contract_version == 1 and role.work_contract_json["reports_to"]
            for section in ("watch_for", "investigate", "correct", "never_let_pass"):
                assert role.work_contract_json[section], (role_name, section)
            assert set(role.memory_scope_json) == {"read", "write"}
            bible = session.scalar(
                select(CharacterBible).where(CharacterBible.employee_id == row.id)
            )
            assert bible is not None, f"{role_name} has no character"
            identity = compose_identity(session, row)
            assert identity.system.startswith(f"You are {row.display_name}, {role_name} at AMN-AI")
            assert f"MISSION: {role.mission}" in identity.system
            assert "NEVER LET PASS:" in identity.system and "STANDING RULES:" in identity.system
            assert f"YOUR CHARACTER: {bible.canonical_name}." in identity.system
            assert "WHAT YOU REMEMBER: nothing yet" in identity.system
            assert identity.context["identity_version"] == "identity-v1"
            assert identity.context["character_id"] == bible.id
            assert identity.context["memory_record_ids"] == []
        sarah = session.get(Agent, staffed["agents"]["Director"].id)
        assert "Show me the evidence" in compose_identity(session, sarah).system


def test_reseeding_keeps_the_owners_contract(client, headers, engine, staffed):
    role_id = staffed["agents"]["Publisher"].role_id
    with Session(engine) as session:
        role = session.get(Role, role_id)
        contract = dict(role.work_contract_json)
        scope = dict(role.memory_scope_json)
    contract["watch_for"] = ["the Owner's own rule about thumbnails"]
    response = client.put(
        f"/api/v1/agents/roles/{role_id}/contract",
        headers=headers,
        json={"contract": {**contract, "memory_scope": scope}, "expected_version": 1},
    )
    assert response.status_code == 200, response.text
    assert response.json()["contract_version"] == 2
    assert seed_role_contracts(engine) == 0
    with Session(engine) as session:
        role = session.get(Role, role_id)
        assert role.work_contract_json["watch_for"] == ["the Owner's own rule about thumbnails"]
        assert role.contract_version == 2
    stale = client.put(
        f"/api/v1/agents/roles/{role_id}/contract",
        headers=headers,
        json={"contract": {**contract, "memory_scope": scope}, "expected_version": 1},
    )
    assert stale.status_code == 422


def test_a_run_carries_the_identity_and_records_what_the_model_was_given(
    client, headers, engine, staffed
):
    registry, model = registry_with(staffed, lambda prompt: "Yes, functional.")
    elena = staffed["agents"]["FactChecker"]
    result = run_agent_task(
        engine, registry, elena.id, "TEST_CONNECTIVITY", "Ești funcțională?", "v1", str(uuid4())
    )
    assert result["status"] == "SUCCEEDED"
    system = model.calls[-1]["system"]
    assert system.startswith("You are Elena (Fact Checker), FactChecker at AMN-AI")
    assert "a SUPPORTED verdict without a verbatim quote" in system
    assert model.calls[-1]["prompt"] == "Ești funcțională?"
    with Session(engine) as session:
        run = session.get(AgentRun, result["id"])
        assert run.context_json["identity_version"] == "identity-v1"
        assert run.context_json["role_name"] == "FactChecker"
        assert run.context_json["system_sha256"]
    view = client.get(f"/api/v1/agents/{elena.id}/identity", headers=headers).json()
    assert view["system_prompt"] == system
    assert view["character"]["canonical_name"] == "Elena Fact-Checker"
    assert view["contract"]["name"] == "FactChecker" and view["memory"] == []


# --------------------------------------------------------------------------- memory


def test_memory_comes_from_real_outcomes_and_is_read_by_role_scope(
    client, headers, engine, staffed
):
    vera, elena = staffed["agents"]["Publisher"], staffed["agents"]["FactChecker"]
    # An Owner decision is studio memory for everyone; nothing invented it.
    with Session(engine) as session:
        version = session.get(OwnerPolicy, 1).version
    change_stop(engine, PolicyCommand(command_id=uuid4(), expected_version=version, stopped=True))
    with Session(engine) as session, session.begin():
        remember(
            session,
            memory_class="AGENT_OPINION",
            content="Held a candidate whose title promised more than the script said.",
            source_type="run",
            agent_id=vera.id,
        )
        remember(
            session,
            memory_class="STRATEGY",
            content="Strategy v2: boost topic space.",
            source_type="event",
        )
        stale = remember(
            session,
            memory_class="TEMP_CONTEXT",
            content="Yesterday's priority.",
            source_type="system",
            agent_id=vera.id,
        )
        stale.expires_at = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        # Writing the same live fact twice stores it once.
        assert (
            remember(
                session,
                memory_class="STRATEGY",
                content="Strategy v2: boost topic space.",
                source_type="event",
            )
            is None
        )
    with Session(engine) as session:
        vera_row, elena_row = session.get(Agent, vera.id), session.get(Agent, elena.id)
        vera_memory = recall(session, vera_row, session.get(Role, vera_row.role_id))
        classes = {(m.memory_class, m.agent_id) for m in vera_memory}
        assert ("OWNER_POLICY", None) in classes
        assert ("STRATEGY", None) in classes
        assert ("AGENT_OPINION", vera.id) in classes
        assert not any(m.content == "Yesterday's priority." for m in vera_memory)
        elena_memory = recall(session, elena_row, session.get(Role, elena_row.role_id))
        elena_classes = {(m.memory_class, m.agent_id) for m in elena_memory}
        assert ("OWNER_POLICY", None) in elena_classes
        assert ("STRATEGY", None) not in elena_classes, "not in the FactChecker's scope"
        assert ("AGENT_OPINION", vera.id) not in elena_classes, "another employee's own memory"
        identity = compose_identity(session, vera_row)
        assert "The Owner stopped autonomy" in identity.system
        assert set(identity.context["memory_record_ids"]) == {m.id for m in vera_memory}
    # The Owner can read and invalidate memory; an invalidated record is no longer told.
    listed = client.get(f"/api/v1/agents/{vera.id}/memory", headers=headers).json()["memory"]
    opinion = next(m for m in listed if m["memory_class"] == "AGENT_OPINION")
    gone = client.post(
        f"/api/v1/agents/{vera.id}/memory/{opinion['id']}/invalidate",
        headers=headers,
        json={"reason": "The hold was mistaken; the title matched the script."},
    )
    assert gone.status_code == 200 and gone.json()["invalidated_at"]
    with Session(engine) as session:
        vera_row = session.get(Agent, vera.id)
        assert opinion["id"] not in {
            m.id for m in recall(session, vera_row, session.get(Role, vera_row.role_id))
        }
        record = session.get(MemoryRecord, opinion["id"])
        assert record.invalidation_reason.startswith("The hold was mistaken")


def test_a_verified_claim_becomes_a_fact_everyone_may_rely_on(engine, staffed):
    """The FactChecker's verdict, quoted from the source, is the only door into VERIFIED_FACT."""
    from app.factual.agent_pipeline import agent_extract_claims, agent_verify_claim
    from app.factual.services import ingest_source_snapshot

    quote = "Telescopul observa in infrarosu."

    def answer(prompt):
        if "evidence_quote" in prompt or "verdict" in prompt.lower():
            return json.dumps(
                {"status": "SUPPORTED", "confidence": 0.9, "evidence_quote": quote, "notes": "ok"}
            )
        return json.dumps(
            [
                {
                    "claim_text": quote,
                    "claim_type": "SCIENTIFIC_FACT",
                    "importance": "CRITICAL",
                    "confidence": 0.9,
                }
            ]
        )

    registry, _ = registry_with(staffed, answer)
    source = ingest_source_snapshot(
        engine,
        url="https://www.iana.org/help/example-domains",
        title="Sursa de proba",
        publisher="www.iana.org",
        author=None,
        raw_content=quote,
        credibility_score=0.9,
        correlation_id=str(uuid4()),
    )
    extracted = agent_extract_claims(engine, registry, source["id"], str(uuid4()))
    claim_id = extracted["claims"][0]["id"]
    agent_verify_claim(engine, registry, claim_id, str(uuid4()))
    with Session(engine) as session:
        fact = session.scalar(
            select(MemoryRecord).where(MemoryRecord.memory_class == "VERIFIED_FACT")
        )
        assert fact is not None and fact.agent_id is None and quote in fact.content
        assert fact.source_type == "run" and session.get(AgentRun, fact.source_id) is not None
        marcus = session.get(Agent, staffed["agents"]["ScriptWriter"].id)
        assert "Supported claim: " + quote in compose_identity(session, marcus).system


# --------------------------------------------------------------------------- reports


def test_stage_reports_are_filed_by_their_owners_and_the_director_decides(
    client, headers, engine, staffed
):
    vera, kael, sarah = (
        staffed["agents"]["Publisher"],
        staffed["agents"]["VideoEditor"],
        staffed["agents"]["Director"],
    )
    outcomes = {
        "publish": {"status": "COMPLETED", "reason": "Publicat pe Canal A: PUBLISHED."},
        "edit_and_qc": {"status": "COMPLETED", "reason": "0 au trecut QC, 1 au picat."},
    }
    filed = file_stage_reports(engine, outcomes, str(uuid4()))
    assert len(filed) == 2
    with Session(engine) as session, session.begin():
        reports = {m.body_json["stage"]: m for m in open_messages(session, inbox=True)}
        assert reports["publish"].from_agent_id == vera.id
        assert reports["edit_and_qc"].from_agent_id == kael.id
        assert all(m.intent == "STATUS" for m in reports.values())
        hold = post_message(
            session,
            intent="ESCALATE",
            subject="Publication HOLD: Galaxy title overstates the script",
            body={
                "media_asset_id": "asset-1",
                "verdict": "HOLD",
                "title": "An honest title",
                "description": "What the script says.",
                "tags": ["space"],
                "hold_reasons": ["title promised a discovery the script does not contain"],
            },
            from_agent_id=vera.id,
        )
        hold_id, qc_report_id = hold.id, reports["edit_and_qc"].id
        assert publication_hold(session, "asset-1")["message_id"] == hold_id
        assert approved_metadata(session, "asset-1") is None

    def answer(prompt):
        assert "director-inbox" in prompt and hold_id in prompt
        return json.dumps(
            {
                "summary": "One hold lifted after reading the reasons; QC failure to be "
                "investigated.",
                "decisions": [
                    {"message_id": hold_id, "action": "APPROVE", "note": "Title now matches."},
                    {
                        "message_id": qc_report_id,
                        "action": "REQUEST_INVESTIGATION",
                        "note": "Which check failed, and on which render?",
                        "assign_to_role": "VideoEditor",
                    },
                    {"message_id": str(uuid4()), "action": "REJECT", "note": "not a message"},
                ],
                "priorities": ["Get one video through QC with real providers."],
            }
        )

    registry, model = registry_with(staffed, answer)
    review = director_review(engine, registry, str(uuid4()), outcomes)
    assert review["reviewed"] == 3 and review["dropped"] == 1
    assert {d["action"] for d in review["applied"]} == {"APPROVE", "REQUEST_INVESTIGATION"}
    assert model.calls[-1]["system"].startswith("You are Sarah (Director), Director at AMN-AI")
    with Session(engine) as session:
        lifted = session.get(AgentMessage, hold_id)
        assert lifted.status == "RESOLVED" and lifted.resolved_by == "Sarah (Director)"
        assert lifted.resolution == "APPROVE: Title now matches."
        assert publication_hold(session, "asset-1") is None
        assert approved_metadata(session, "asset-1")["title"] == "An honest title"
        answered = session.get(AgentMessage, qc_report_id)
        assert answered.status == "ANSWERED"
        request = session.scalar(select(AgentMessage).where(AgentMessage.intent == "REQUEST_INFO"))
        assert request.from_agent_id == sarah.id and request.to_agent_id == kael.id
        assert request.body_json["about_message_id"] == qc_report_id
        opinion = session.scalar(
            select(MemoryRecord).where(
                MemoryRecord.agent_id == sarah.id, MemoryRecord.memory_class == "AGENT_OPINION"
            )
        )
        assert opinion.content.startswith("Daily review: One hold lifted")
        assert session.scalar(
            select(DomainEvent).where(DomainEvent.event_type == "director.review_completed")
        )
        # Kael sees the request in his identity; the publish report was acknowledged nobody's
        # business but Sarah's, so it stays open until she reads it.
        kael_row = session.get(Agent, kael.id)
        assert "Investigate: edit_and_qc" not in compose_identity(session, kael_row).system
    listed = client.get("/api/v1/agents/messages?status=OPEN", headers=headers).json()["messages"]
    assert {m["intent"] for m in listed} == {"STATUS", "REQUEST_INFO"}
    # The Owner may ask for a review at any time; the app's own registry has no model here,
    # so the Director cannot run and the API says so instead of pretending.
    on_demand = client.post("/api/v1/agents/director/review", headers=headers)
    assert on_demand.status_code == 422 and "no usable review" in on_demand.json()["detail"]


def test_a_malformed_review_decides_nothing(engine, staffed):
    registry, _ = registry_with(staffed, lambda prompt: "I think everything is fine.")
    with Session(engine) as session, session.begin():
        post_message(session, intent="STATUS", subject="media: COMPLETED", body={"stage": "media"})
    with pytest.raises(DirectorError):
        director_review(engine, registry, str(uuid4()))
    with Session(engine) as session:
        assert len(open_messages(session, inbox=True)) == 1
        assert session.scalar(select(MemoryRecord)) is None


# --------------------------------------------------------------------------- judgement tasks


def test_the_voice_artist_reviews_narration_and_a_flag_escalates(engine, tmp_path, staffed):
    lyra = staffed["agents"]["VoiceArtist"]
    storyboard_id = make_storyboard(engine, tmp_path)

    def flag(prompt):
        assert "storyboard-narration" in prompt and "Narration 1." in prompt
        return json.dumps(
            {
                "verdict": "FLAG",
                "notes": ["Scene 2 cannot be spoken in 6 seconds."],
                "pronunciation": [{"scene_index": 1, "term": "AMN", "hint": "A-M-N"}],
            }
        )

    registry, model = registry_with(staffed, flag)
    review = review_narration(engine, registry, storyboard_id, str(uuid4()))
    assert review["verdict"] == "FLAG" and review["pronunciation"][0]["hint"] == "A-M-N"
    assert model.calls[-1]["system"].startswith("You are Lyra (Voice Artist), VoiceArtist")
    with Session(engine) as session:
        message = session.get(AgentMessage, review["message_id"])
        assert message.intent == "ESCALATE" and message.from_agent_id == lyra.id
        assert message.body_json["storyboard_id"] == storyboard_id
        opinion = session.scalar(select(MemoryRecord).where(MemoryRecord.agent_id == lyra.id))
        assert opinion.memory_class == "AGENT_OPINION" and "FLAG" in opinion.content

    # A structured blocker is an escalation with its reason, not a guess.
    registry, _ = registry_with(
        staffed,
        lambda prompt: json.dumps(
            {"blocker": {"reason": "No voice is selected for this connection", "needs": "a voice"}}
        ),
    )
    blocked = review_narration(engine, registry, storyboard_id, str(uuid4()))
    assert blocked["verdict"] == "BLOCKED" and "No voice is selected" in blocked["reason"]

    # Prose instead of the schema stores no verdict at all.
    registry, _ = registry_with(staffed, lambda prompt: "Sounds fine to me!")
    with Session(engine) as session:
        before = session.scalar(select(AgentMessage.id).order_by(AgentMessage.created_at.desc()))
    with pytest.raises(ReviewError):
        review_narration(engine, registry, storyboard_id, str(uuid4()))
    with Session(engine) as session:
        assert (
            session.scalar(select(AgentMessage.id).order_by(AgentMessage.created_at.desc()))
            == before
        )
