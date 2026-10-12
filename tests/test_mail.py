"""Correspondence: letters in threads, employees who answer them, and what stopped the day.

Local tests with a scripted model; nothing reaches a vendor. What is asserted: a reply and a
forward inherit their thread and the thread reads in order; a letter reaches the addressee's
prompt with its earlier exchange; an employee answers a letter in its thread and a question
closes while an instruction stays open until the work is done; the worker answers only what
is waiting and nothing while autonomy is stopped; the Owner can read a thread, reply and
forward through the API. And the failures of 2026-09-11: the real adapter asks for thinking
off, a stale THINKING flag no longer blocks an employee, a run is a record while it runs, and
the day finishes the media setup the account already determines.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.agents.identity import compose_identity
from app.agents.mail import (
    MailError,
    answer_mail,
    correspondence_round,
    letters_awaiting_answer,
)
from app.agents.messages import (
    forward_message,
    letters_for_owner,
    open_messages,
    post_message,
    thread_messages,
    thread_view,
)
from app.agents.models import Agent, AgentMessage, AgentRun, ModelRecord, Role
from app.agents.services import run_agent_task, seed_initial_workforce
from app.integrations.llm import ConfiguredLLM
from app.media.services import seed_default_character_bibles
from app.models import DomainEvent, OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.runbook import services as runbook_services
from app.workflows.worker import worker_pass
from sqlalchemy import select
from sqlalchemy.orm import Session

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


def session_events(engine, event_type):
    with Session(engine) as session:
        return session.scalars(
            select(DomainEvent)
            .where(DomainEvent.event_type == event_type)
            .order_by(DomainEvent.sequence)
        ).all()


def letter_json(reply, done=False, needs=""):
    return lambda prompt: json.dumps(
        {"reply": reply, "done": done, "needs": needs}, ensure_ascii=False
    )


# --------------------------------------------------------------------------- threads


def test_a_reply_and_a_forward_stay_in_the_thread_and_the_thread_reads_in_order(engine, staffed):
    sarah, elena, marcus = (
        staffed["agents"]["Director"],
        staffed["agents"]["FactChecker"],
        staffed["agents"]["ScriptWriter"],
    )
    with Session(engine) as session, session.begin():
        first = post_message(
            session,
            intent="REQUEST_INFO",
            subject="Afirmația despre 40% — ce sursă?",
            body_text="Elena, spune-mi pe ce sursă stă cifra de 40%. Sarah",
            from_agent_id=sarah.id,
            to_agent_id=elena.id,
        )
        reply = post_message(
            session,
            intent="STATUS",
            subject="Re: Afirmația despre 40% — ce sursă?",
            body_text="Stă pe raportul IEA din 2025, pagina 12. Elena",
            from_agent_id=elena.id,
            to_agent_id=sarah.id,
            in_reply_to=first.id,
        )
        fwd = forward_message(
            session,
            reply.id,
            to_agent_id=marcus.id,
            from_agent_id=sarah.id,
            note="Marcus, sursa e bună; păstrează cifra în scenariu. Sarah",
        )
        ids = (first.id, reply.id, fwd.id)
    with Session(engine) as session:
        rows = thread_messages(session, ids[0])
        assert [r.id for r in rows] == list(ids)
        assert {r.thread_id for r in rows} == {ids[0]}
        assert rows[1].in_reply_to == ids[0] and rows[2].in_reply_to == ids[1]
        assert rows[2].intent == "HANDOFF" and rows[2].subject.startswith("Fwd: Re:")
        assert rows[2].to_agent_id == marcus.id
    view = thread_view(engine, ids[0])
    assert view["subject"] == "Afirmația despre 40% — ce sursă?"
    assert [m["from_name"] for m in view["messages"]] == [
        sarah.display_name,
        elena.display_name,
        sarah.display_name,
    ]
    assert view["messages"][2]["to_name"] == marcus.display_name
    assert "raportul IEA" in view["messages"][1]["body_text"]


def test_a_letter_reaches_the_addressee_with_the_earlier_exchange(engine, staffed):
    sarah, elena = staffed["agents"]["Director"], staffed["agents"]["FactChecker"]
    with Session(engine) as session, session.begin():
        first = post_message(
            session,
            intent="STATUS",
            subject="Verificare: 3 afirmații",
            body_text="Am verificat trei afirmații; a treia nu are sursă. Elena",
            from_agent_id=elena.id,
            to_agent_id=None,
        )
        post_message(
            session,
            intent="REQUEST_INFO",
            subject="Re: Verificare: 3 afirmații",
            body_text="Caută o sursă pentru a treia până diseară. Sarah",
            from_agent_id=sarah.id,
            to_agent_id=elena.id,
            in_reply_to=first.id,
        )
    with Session(engine) as session:
        system = compose_identity(session, session.get(Agent, elena.id)).system
    assert "Caută o sursă pentru a treia până diseară" in system
    assert "earlier, Elena (Fact Checker): Verificare: 3 afirmații" in system
    assert "a treia nu are sursă" in system


# --------------------------------------------------------------------------- answering


def test_an_employee_answers_a_question_in_its_thread_and_the_question_closes(engine, staffed):
    sarah, elena = staffed["agents"]["Director"], staffed["agents"]["FactChecker"]
    with Session(engine) as session, session.begin():
        asked = post_message(
            session,
            intent="REQUEST_INFO",
            subject="Ce sursă are cifra de 40%?",
            body_text="Elena, pe ce stă 40%? Sarah",
            from_agent_id=sarah.id,
            to_agent_id=elena.id,
        )
        asked_id = asked.id
    registry, model = registry_with(
        staffed, letter_json("Sarah, cifra stă pe raportul IEA 2025, p. 12. Elena", done=True)
    )

    sent = answer_mail(engine, registry, asked_id)

    assert "mail-thread" in model.calls[-1]["prompt"]
    assert "Elena, pe ce stă 40%?" in model.calls[-1]["prompt"]
    assert model.calls[-1]["system"].startswith("You are Elena (Fact Checker)")
    with Session(engine) as session:
        reply = session.get(AgentMessage, sent["message_id"])
        assert reply.thread_id == asked_id and reply.in_reply_to == asked_id
        # Her answer to the Director goes to the Director's inbox, where the review reads it.
        assert reply.from_agent_id == elena.id and reply.to_agent_id is None
        assert reply.body_text.startswith("Sarah, cifra stă pe raportul IEA")
        original = session.get(AgentMessage, asked_id)
        assert original.status == "ANSWERED"
        assert original.resolved_by == elena.display_name
        run = session.get(AgentRun, sent["run_id"])
        assert run.task_type == "answer_mail"
        assert run.context_json["task_summary"].startswith("Răspund la «Ce sursă are cifra")


def test_an_instruction_stays_open_until_the_employee_says_the_work_is_done(engine, staffed):
    sarah, lyra = staffed["agents"]["Director"], staffed["agents"]["VoiceArtist"]
    with Session(engine) as session, session.begin():
        handoff = post_message(
            session,
            intent="HANDOFF",
            subject="Narațiune mai caldă pe episodul 3",
            body_text="Lyra, refă narațiunea cu un ton mai cald. Sarah",
            from_agent_id=sarah.id,
            to_agent_id=lyra.id,
        )
        handoff_id = handoff.id
    registry, _ = registry_with(staffed, letter_json("Mă apuc; gata până diseară. Lyra"))
    answer_mail(engine, registry, handoff_id)
    with Session(engine) as session:
        assert session.get(AgentMessage, handoff_id).status == "OPEN"
        # Her own word is the last on the thread: nothing more to answer for now.
        assert letters_awaiting_answer(session) == []

    registry, _ = registry_with(staffed, letter_json("Gata, narațiunea e refăcută. Lyra", True))
    with Session(engine) as session, session.begin():
        asked_id = post_message(
            session,
            intent="REQUEST_INFO",
            subject="Re: Narațiune mai caldă pe episodul 3",
            body_text="E gata?",
            from_agent_id=sarah.id,
            to_agent_id=lyra.id,
            in_reply_to=handoff_id,
        ).id
    with Session(engine) as session:
        # She wrote in the thread a moment ago: the question waits a quarter of an hour, and
        # then it is the newest letter to her that she answers, not the handoff.
        assert letters_awaiting_answer(session) == []
        later = datetime.now(UTC) + timedelta(minutes=16)
        assert letters_awaiting_answer(session, now=later) == [asked_id]
    sent = answer_mail(engine, registry, asked_id)
    with Session(engine) as session:
        assert session.get(AgentMessage, sent["message_id"]).in_reply_to == asked_id
        assert session.get(AgentMessage, asked_id).status == "ANSWERED"
        # "Gata" is her word that the work is done: the handoff closes with the answer.
        assert session.get(AgentMessage, handoff_id).status == "ANSWERED"


def test_prose_instead_of_the_schema_is_still_a_letter(engine, staffed):
    sarah, kael = staffed["agents"]["Director"], staffed["agents"]["VideoEditor"]
    with Session(engine) as session, session.begin():
        asked = post_message(
            session,
            intent="REQUEST_INFO",
            subject="Care randare a picat?",
            from_agent_id=sarah.id,
            to_agent_id=kael.id,
        )
        asked_id = asked.id
    registry, _ = registry_with(staffed, lambda p: "Sarah, a picat randarea 7, codec lipsă. Kael")
    sent = answer_mail(engine, registry, asked_id)
    with Session(engine) as session:
        assert session.get(AgentMessage, sent["message_id"]).body_text.startswith("Sarah, a picat")


def test_a_schema_example_echoed_back_is_not_a_letter_and_the_second_try_is(engine, staffed):
    """Nadia narrated and restated the example object; her letter read "..."."""
    sarah, nadia = staffed["agents"]["Director"], staffed["agents"]["Accountant"]
    with Session(engine) as session, session.begin():
        asked = post_message(
            session,
            intent="REQUEST_INFO",
            subject="Investigate: books",
            body_text="Show me the evidence behind the zero. Sarah",
            from_agent_id=sarah.id,
            to_agent_id=nadia.id,
        )
        asked_id = asked.id
    calls: list = []

    class Narrator(ScriptedModel):
        async def generate(self, model, prompt, **kwargs):
            calls.append(kwargs.get("extra"))
            if kwargs.get("extra") == {"think": True}:
                text = json.dumps(
                    {
                        "reply": "Sarah, cele 59 de rulări sunt pe un model fără preț. Nadia",
                        "done": True,
                    }
                )
            else:
                text = (
                    'Let me think. The instructions say: Return only JSON: {"reply": "...", '
                    '"done": true|false, "needs": "..."}. So, the runs are'
                )
            return GenerateResult(text, 10, 40, None)

    registry = ProviderRegistry()
    registry.register(staffed["provider_id"], Narrator(lambda p: ""))
    sent = answer_mail(engine, registry, asked_id)
    assert calls == [{"format": "json"}, {"think": True}]
    with Session(engine) as session:
        reply = session.get(AgentMessage, sent["message_id"])
        assert reply.body_text.startswith("Sarah, cele 59 de rulări")


def test_an_employee_who_cannot_do_what_is_asked_says_so_in_words(engine, staffed):
    """Lyra answered a render question with a JSON blocker pasted into the letter."""
    sarah, lyra = staffed["agents"]["Director"], staffed["agents"]["VoiceArtist"]
    with Session(engine) as session, session.begin():
        asked = post_message(
            session,
            intent="REQUEST_INFO",
            subject="Investigate: renders failed QC",
            body_text="Find the root cause. Sarah",
            from_agent_id=sarah.id,
            to_agent_id=lyra.id,
        )
        asked_id = asked.id
    registry, _ = registry_with(
        staffed,
        lambda p: json.dumps(
            {
                "blocker": {
                    "reason": "I do not have access to the render logs.",
                    "needs": "The render job logs.",
                }
            }
        ),
    )
    sent = answer_mail(engine, registry, asked_id)
    with Session(engine) as session:
        reply = session.get(AgentMessage, sent["message_id"])
        assert reply.intent == "ESCALATE"
        assert reply.body_text.startswith("Nu pot răspunde la asta: I do not have access")
        assert "Am nevoie de: The render job logs." in reply.body_text
        assert "{" not in reply.body_text
    assert sent["needs"] == "The render job logs."


def test_a_letter_to_nobody_or_to_a_departed_employee_is_not_answered(engine, staffed):
    elena = staffed["agents"]["FactChecker"]
    with Session(engine) as session, session.begin():
        inbox = post_message(session, intent="STATUS", subject="Raport", from_agent_id=elena.id)
        inbox_id = inbox.id
        session.get(Agent, elena.id).lifecycle = "TERMINATED"
        gone = post_message(session, intent="REQUEST_INFO", subject="?", to_agent_id=elena.id)
        gone_id = gone.id
    registry, _ = registry_with(staffed, lambda p: "{}")
    with pytest.raises(MailError):
        answer_mail(engine, registry, inbox_id)
    with pytest.raises(MailError):
        answer_mail(engine, registry, gone_id)


def test_the_worker_answers_the_waiting_mail_and_nothing_while_autonomy_is_stopped(
    engine, settings, staffed
):
    sarah, elena = staffed["agents"]["Director"], staffed["agents"]["FactChecker"]
    with Session(engine) as session, session.begin():
        post_message(
            session,
            intent="REQUEST_INFO",
            subject="Sursa?",
            body_text="Care e sursa? Sarah",
            from_agent_id=sarah.id,
            to_agent_id=elena.id,
        )

    def answer(prompt):
        # Elena answers the letter; Sarah, reading her inbox afterwards, acknowledges it.
        if "director-inbox" in prompt:
            ids = re.findall(r'"id": "([0-9a-f-]{36})"', prompt)
            return json.dumps(
                {
                    "summary": "Sursa e clară; nimic de cerut.",
                    "decisions": [{"message_id": i, "action": "ACKNOWLEDGE"} for i in ids],
                }
            )
        return json.dumps({"reply": "Raportul IEA. Elena", "done": True, "needs": ""})

    registry, model = registry_with(staffed, answer)

    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = True
    assert correspondence_round(engine, registry)["reason"] == "autonomy stopped"
    assert model.calls == []

    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    summary = worker_pass(engine, {}, registry=registry)
    assert len(summary["mail"]["answered"]) == 1 and summary["mail"]["refused"] == []
    # Elena's answer to the Director lands in the inbox, and the Director reads it at once.
    assert summary["mail"]["review"]["reviewed"] >= 1
    assert [c["system"][:15] for c in model.calls] == ["You are Elena (", "You are Sarah ("]
    with Session(engine) as session:
        reply = session.scalar(select(AgentMessage).where(AgentMessage.from_agent_id == elena.id))
        assert reply.to_agent_id is None
    # Nothing is owed any more: the next pass answers nothing and reviews nothing.
    again = worker_pass(engine, {}, registry=registry)
    assert again["mail"]["answered"] == [] and again["mail"]["review"] is None
    assert len(model.calls) == 2


def test_a_report_waits_for_nobody_and_a_long_thread_is_left_to_the_evening(engine, staffed):
    sarah, elena = staffed["agents"]["Director"], staffed["agents"]["FactChecker"]
    with Session(engine) as session, session.begin():
        post_message(
            session,
            intent="STATUS",
            subject="Raport de verificare",
            body_text="Trei afirmații verificate. Elena",
            from_agent_id=elena.id,
            to_agent_id=sarah.id,
        )
        first = post_message(
            session,
            intent="REQUEST_INFO",
            subject="Sursa?",
            from_agent_id=sarah.id,
            to_agent_id=elena.id,
        )
        for i in range(7):
            post_message(
                session,
                intent="REQUEST_INFO",
                subject=f"Și încă ceva ({i})",
                from_agent_id=sarah.id,
                to_agent_id=elena.id,
                in_reply_to=first.id,
            )
    with Session(engine) as session:
        assert letters_awaiting_answer(session) == []


def test_the_owner_reads_a_thread_and_writes_into_it_through_the_api(
    client, headers, engine, staffed
):
    sarah, elena, marcus = (
        staffed["agents"]["Director"],
        staffed["agents"]["FactChecker"],
        staffed["agents"]["ScriptWriter"],
    )
    with Session(engine) as session, session.begin():
        first = post_message(
            session,
            intent="REQUEST_INFO",
            subject="Sursa cifrei",
            body_text="Elena, sursa? Sarah",
            from_agent_id=sarah.id,
            to_agent_id=elena.id,
        )
        first_id = first.id

    reply = client.post(
        f"/api/v1/agents/messages/{first_id}/reply",
        json={"text": "Sarah, vreau și eu sursa asta pe masă. Owner"},
        headers=headers,
    )
    assert reply.status_code == 200
    assert reply.json()["thread_id"] == first_id
    assert reply.json()["to_agent_id"] == sarah.id and reply.json()["from_agent_id"] is None

    fwd = client.post(
        f"/api/v1/agents/messages/{first_id}/forward",
        json={"to_agent_id": marcus.id, "note": "Marcus, urmărește și tu firul. Owner"},
        headers=headers,
    )
    assert fwd.status_code == 200 and fwd.json()["intent"] == "HANDOFF"

    thread = client.get(f"/api/v1/agents/messages/threads/{first_id}", headers=headers).json()
    assert [m["subject"] for m in thread["messages"]] == [
        "Sursa cifrei",
        "Re: Sursa cifrei",
        "Fwd: Sursa cifrei",
    ]
    assert thread["messages"][1]["body_text"].startswith("Sarah, vreau")
    assert (
        client.get("/api/v1/agents/messages/threads/" + "0" * 36, headers=headers).json()[
            "messages"
        ]
        == []
    )


# --------------------------------------------------------------------------- the Owner


def test_the_director_writes_to_the_owner_when_a_decision_is_the_owners(engine, staffed):
    """An ESCALATE_TO_OWNER decision on a matter that is his (his account's sign-in,
    2026-10-12: a title or a prompt is hers) is a letter to the Owner, in the thread, out of
    the Director's own inbox, and the Owner's reply closes it and reaches the Director."""
    vera = staffed["agents"]["Publisher"]
    with Session(engine) as session, session.begin():
        hold = post_message(
            session,
            intent="ESCALATE",
            subject="Publication HOLD: contul YouTube cere re-autentificare",
            body_text="Token-ul canalului a expirat; nu pot publica. Vera",
            from_agent_id=vera.id,
        )
        hold_id = hold.id

    def answer(prompt):
        return json.dumps(
            {
                "summary": "Autentificarea contului este a Owner-ului.",
                "decisions": [
                    {
                        "message_id": hold_id,
                        "action": "ESCALATE_TO_OWNER",
                        "note": "Am nevoie să te autentifici din nou pe canal.",
                    }
                ],
            }
        )

    registry, _ = registry_with(staffed, answer)
    from app.agents.director import director_review

    director_review(engine, registry, str(uuid4()))
    letters = letters_for_owner(engine)
    assert len(letters) == 1
    letter = letters[0]
    assert letter["for_owner"] is True and letter["to_name"] == "Owner"
    assert letter["thread_id"] == hold_id
    assert letter["body_text"].startswith("Am nevoie să te autentifici")
    assert letter["from_name"] == staffed["agents"]["Director"].display_name
    with Session(engine) as session:
        # Not the Director's to review: the inbox holds the hold, not her own letter.
        assert letter["id"] not in {m.id for m in open_messages(session, inbox=True)}
    events = [
        e
        for e in session_events(engine, "agent.message_posted")
        if e.payload.get("for_owner") is True
    ]
    assert events and events[-1].payload["to_name"] == "Owner"


def test_the_owner_answers_a_letter_and_the_director_writes_back_to_the_owner(
    client, headers, engine, staffed
):
    sarah = staffed["agents"]["Director"]
    from app.agents.director import letter_to_owner

    letter_id = letter_to_owner(
        engine, "Ziua s-a oprit la etapa «media»", "Randarea nu a pornit: cheia Runway. — Sarah"
    )
    assert (
        client.get("/api/v1/agents/messages/owner", headers=headers).json()["letters"][0]["id"]
        == letter_id
    )

    reply = client.post(
        f"/api/v1/agents/messages/{letter_id}/reply",
        json={"text": "Am reînnoit cheia Runway. Pornește din nou mâine dimineață. Owner"},
        headers=headers,
    )
    assert reply.status_code == 200 and reply.json()["to_agent_id"] == sarah.id
    with Session(engine) as session:
        answered = session.get(AgentMessage, letter_id)
        assert answered.status == "ANSWERED" and answered.resolved_by == "Owner"
        assert "Am reînnoit cheia" in answered.resolution
    assert client.get("/api/v1/agents/messages/owner", headers=headers).json()["letters"] == []

    # Sarah answers the Owner's letter — and her answer is addressed to the Owner, in red.
    registry, _ = registry_with(
        staffed, letter_json("Mulțumesc. Pornesc rularea mâine la 09:00. Sarah", done=True)
    )
    with Session(engine) as session:
        waiting = letters_awaiting_answer(session)
    assert waiting == [reply.json()["id"]]
    sent = answer_mail(engine, registry, waiting[0])
    with Session(engine) as session:
        back = session.get(AgentMessage, sent["message_id"])
        assert back.to_agent_id is None and back.body_json["to"] == "Owner"
        assert back.thread_id == letter_id
    assert [x["id"] for x in letters_for_owner(engine)] == [sent["message_id"]]


def test_a_day_that_stops_writes_to_the_owner_where_and_why(engine, settings, staffed, tmp_path):
    from app.integrations.vault import CredentialVault
    from app.runbook.services import execute_daily_run

    settings.ffmpeg_path = settings.ffmpeg_path or "ffmpeg-test-stub"
    runners = {"media": lambda: {"status": "FAILED", "reason": "Randarea a picat: cheia Runway."}}
    result = execute_daily_run(
        engine, settings, CredentialVault(tmp_path / "k"), stage_runners=runners
    )
    assert result["stopped_at_stage"] == "media"
    letters = letters_for_owner(engine)
    assert letters and letters[0]["subject"] == "Ziua s-a oprit la etapa «producție media»"
    assert "cheia Runway" in letters[0]["body_text"]


# --------------------------------------------------------------------------- 2026-09-11


def test_the_configured_adapter_asks_ollama_for_thinking_off_and_reports_how_it_ended(
    monkeypatch,
):
    """The studio's connections run through ConfiguredLLM, not the seeded local adapter."""
    seen: dict = {}

    def request(self, method, path, body=None):
        seen.update({"path": path, "body": body})
        return {"response": "", "thinking": "x" * 500, "done_reason": "length", "eval_count": 702}

    monkeypatch.setattr(ConfiguredLLM, "request", request)
    adapter = ConfiguredLLM("ollama", {"base_url": "https://ollama.com"}, {"api_key": "k"})
    import asyncio

    result = asyncio.run(adapter.generate("qwen3.5:397b", "Verify", max_tokens=700))
    assert seen["path"] == "/api/generate" and seen["body"]["think"] is False
    assert seen["body"]["options"]["num_predict"] == 700
    assert result.text == "" and result.raw_response["done_reason"] == "length"
    assert "thinking" not in result.raw_response


def test_a_stale_thinking_flag_no_longer_refuses_the_employee(engine, staffed):
    """Dr. Aris sat in THINKING for a day and every stage was refused 'already has a task'."""
    aris = staffed["agents"]["LeadResearcher"]
    with Session(engine) as session, session.begin():
        session.get(Agent, aris.id).runtime_state = "THINKING"
    registry, _ = registry_with(staffed, lambda p: "Am trei idei.")

    result = run_agent_task(engine, registry, aris.id, "propose_topics", "Idei", "v1", str(uuid4()))

    assert result["status"] == "SUCCEEDED"
    with Session(engine) as session:
        assert session.get(Agent, aris.id).runtime_state == "IDLE"


def test_a_run_is_a_record_while_it_runs_and_an_abandoned_one_is_closed(engine, staffed):
    aris = staffed["agents"]["LeadResearcher"]
    seen: dict = {}

    class Peeking(ScriptedModel):
        async def generate(self, model, prompt, **kwargs):
            with Session(engine) as session:
                running = session.scalars(
                    select(AgentRun).where(
                        AgentRun.agent_id == aris.id, AgentRun.status == "RUNNING"
                    )
                ).all()
                seen["running"] = [(r.task_type, r.finished_at) for r in running]
            return GenerateResult("Gata.", 1, 1, None)

    registry = ProviderRegistry()
    registry.register(staffed["provider_id"], Peeking(lambda p: ""))
    result = run_agent_task(
        engine, registry, aris.id, "gather_sources", "Surse", "v1", str(uuid4())
    )
    assert seen["running"] == [("gather_sources", None)]
    with Session(engine) as session:
        assert session.get(AgentRun, result["id"]).status == "SUCCEEDED"

    # A RUNNING row older than the stale limit is what a killed process leaves behind.
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    with Session(engine) as session, session.begin():
        session.add(
            AgentRun(
                id=str(uuid4()),
                agent_id=aris.id,
                task_type="extract_claims",
                objective="x",
                prompt_template_version="v1",
                model_name="m",
                provider_name="p",
                status="RUNNING",
                correlation_id=str(uuid4()),
                started_at=old,
                context_json={},
            )
        )
        session.get(Agent, aris.id).runtime_state = "THINKING"
    result = run_agent_task(
        engine, registry, aris.id, "gather_sources", "Surse", "v1", str(uuid4())
    )
    assert result["status"] == "SUCCEEDED"
    with Session(engine) as session:
        statuses = {
            r.task_type: r.status
            for r in session.scalars(select(AgentRun).where(AgentRun.agent_id == aris.id))
        }
        assert statuses["extract_claims"] == "ABANDONED"


def test_the_day_finishes_the_media_setup_the_account_already_determines(monkeypatch, engine):
    calls: list[str] = []
    monkeypatch.setattr(
        "app.media.factory.media_readiness",
        lambda e, v: {"image": {"status": "NO_DEFAULT"}, "voice": {"status": "READY"}},
    )
    monkeypatch.setattr(
        "app.integrations.autoconfig.auto_configure",
        lambda e, v: calls.append("auto_configure") or {"applied": []},
    )
    assert runbook_services.finish_media_setup(engine, None) == {"applied": []}
    assert calls == ["auto_configure"]

    monkeypatch.setattr(
        "app.media.factory.media_readiness",
        lambda e, v: {"image": {"status": "READY"}, "voice": {"status": "READY"}},
    )
    assert runbook_services.finish_media_setup(engine, None) is None
    assert calls == ["auto_configure"]


def test_an_analysis_without_its_object_is_asked_again_with_native_thinking(engine, staffed):
    """The Director wrote twelve thousand tokens of analysis and never reached the JSON; asked
    to format it she narrated again. The second try is the same question with her own
    thinking on, and that one answers with the object."""
    from app.agents.director import director_review

    vera = staffed["agents"]["Publisher"]
    with Session(engine) as session, session.begin():
        hold = post_message(
            session,
            intent="ESCALATE",
            subject="Publication HOLD: title",
            body_text="Nu public.",
            from_agent_id=vera.id,
        )
        hold_id = hold.id
    calls: list[dict] = []

    class Narrator(ScriptedModel):
        async def generate(self, model, prompt, **kwargs):
            calls.append({"prompt": prompt, "extra": kwargs.get("extra")})
            if kwargs.get("extra") == {"think": True}:
                text = json.dumps(
                    {
                        "summary": "Hold read; nothing to add.",
                        "decisions": [{"message_id": hold_id, "action": "ACKNOWLEDGE"}],
                    }
                )
            else:
                text = (
                    "Let me work through this inbox carefully. 1. `" + hold_id + "` — Vera, "
                    "HOLD: I will ACKNOWLEDGE this; the title needs the Owner. {not the object}"
                )
            return GenerateResult(text, 10, 40, None)

    registry = ProviderRegistry()
    registry.register(staffed["provider_id"], Narrator(lambda p: ""))
    result = director_review(engine, registry, str(uuid4()))

    assert result["reviewed"] == 1
    assert [c["extra"] for c in calls] == [{"format": "json"}, {"think": True}]
    assert calls[0]["prompt"] == calls[1]["prompt"]
    with Session(engine) as session:
        runs = session.scalars(
            select(AgentRun).where(AgentRun.task_type == "director_review")
        ).all()
        assert sorted(r.prompt_template_version for r in runs) == [
            "director-review-v1",
            "director-review-v1+think",
        ]
        assert session.get(AgentMessage, hold_id).status == "RESOLVED"


# ------------------------------------------------------------------- a review that fed itself


def _decide_all(action, **fields):
    """A Director model that gives every message in the inbox the same decision."""
    return lambda prompt: json.dumps(
        {
            "summary": "Decis.",
            "decisions": [
                {"message_id": i, "action": action, **fields}
                for i in re.findall(r'"id": "([0-9a-f-]{36})"', prompt)
            ],
        },
        ensure_ascii=False,
    )


def test_an_escalated_matter_leaves_the_inbox_and_the_owner_is_asked_once(engine, staffed):
    """One evening the Owner was asked the same question nine times: the escalated message
    stayed open, every review found it and wrote again. Escalated is decided — the message
    is answered, and the same matter raised again by the next run is the same letter."""
    from app.agents.director import director_review

    vera = staffed["agents"]["Publisher"]
    subject = "Nicio sursă preluată pentru «Descoperire Robotică Autonomă»"
    with Session(engine) as session, session.begin():
        first = post_message(
            session,
            intent="ESCALATE",
            subject=subject,
            body_text="Nimic nu se descarcă. Vera",
            from_agent_id=vera.id,
        ).id
    registry, _ = registry_with(
        staffed, _decide_all("ESCALATE_TO_OWNER", note="Autorizează un site pentru subiect.")
    )

    director_review(engine, registry, str(uuid4()))
    with Session(engine) as session:
        assert session.get(AgentMessage, first).status == "ANSWERED"
        assert open_messages(session, inbox=True) == []
    assert len(letters_for_owner(engine)) == 1

    with Session(engine) as session, session.begin():
        second = post_message(
            session,
            intent="ESCALATE",
            subject=subject,
            body_text="Tot nimic. Vera",
            from_agent_id=vera.id,
        ).id
    director_review(engine, registry, str(uuid4()))
    with Session(engine) as session:
        assert session.get(AgentMessage, second).status == "ANSWERED"
    letters = letters_for_owner(engine)
    assert len(letters) == 1 and letters[0]["thread_id"] == first


def test_an_answer_to_an_investigation_is_read_not_investigated_again(engine, staffed):
    """'Investigate: Re: Investigate: …' was a conversation feeding itself. The answer to
    her investigation is read; what she owes after it is a decision, not a question."""
    from app.agents.director import director_review

    aris = staffed["agents"]["LeadResearcher"]
    with Session(engine) as session, session.begin():
        answer = post_message(
            session,
            intent="STATUS",
            subject="Re: Investigate: idea_generation: COMPLETED — 0 teme propuse",
            body_text="Am propus cinci; toate pe un site neautorizat. Aris",
            from_agent_id=aris.id,
        ).id
    registry, _ = registry_with(
        staffed,
        _decide_all("REQUEST_INVESTIGATION", assign_to_role="LeadResearcher", note="Care site?"),
    )

    director_review(engine, registry, str(uuid4()))
    with Session(engine) as session:
        row = session.get(AgentMessage, answer)
        assert row.status == "RESOLVED" and row.resolution.startswith("Luat la cunoștință")
        # An answer titled with the old English prefix is still recognised as one.
        for prefix in ("Investigate: Re:%", "De investigat: Re:%"):
            assert (
                session.scalar(select(AgentMessage).where(AgentMessage.subject.like(prefix)))
                is None
            )


def test_reviews_are_rationed_by_the_hour(engine, staffed):
    """Nine reviews in twenty-four minutes cost two hundred thousand tokens. After the hour's
    ration the answers still get written; the review of them waits."""
    from app.agents.mail import REVIEWS_PER_HOUR
    from app.services import utc_now

    sarah, elena = staffed["agents"]["Director"], staffed["agents"]["FactChecker"]
    with Session(engine) as session, session.begin():
        for _ in range(REVIEWS_PER_HOUR):
            session.add(
                AgentRun(
                    id=str(uuid4()),
                    agent_id=sarah.id,
                    task_type="director_review",
                    objective="review",
                    prompt_template_version="director-review-v1",
                    model_name="m",
                    provider_name="p",
                    status="SUCCEEDED",
                    correlation_id=str(uuid4()),
                    started_at=utc_now(),
                    context_json={},
                )
            )
        post_message(
            session,
            intent="REQUEST_INFO",
            subject="Sursa?",
            body_text="Care e sursa? Sarah",
            from_agent_id=sarah.id,
            to_agent_id=elena.id,
        )
    registry, model = registry_with(staffed, letter_json("Raportul IEA. Elena", done=True))

    result = correspondence_round(engine, registry)
    assert len(result["answered"]) == 1 and "deferred" in result["review"]
    assert [c["system"][:15] for c in model.calls] == ["You are Elena ("]


def test_owner_reply_survives_another_writer_committing_after_the_parent_is_read(
    client, headers, engine, staffed
):
    from threading import Event, Thread

    from app.agents.director import letter_to_owner
    from sqlalchemy import event

    letter_id = letter_to_owner(engine, "Concurrent reply scenario", "Please answer this letter.")
    writer_finished = Event()
    writer_errors = []
    threads = []

    def competing_write():
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "UPDATE owner_policy SET version = version + 1 WHERE id = 1"
                )
        except Exception as exc:
            writer_errors.append(exc)
        finally:
            writer_finished.set()

    def after_parent_read(connection, cursor, statement, parameters, context, executemany):
        if "FROM agent_message" not in statement or letter_id not in parameters or threads:
            return
        thread = Thread(target=competing_write)
        threads.append(thread)
        thread.start()
        # Without a write lock the competing commit invalidates the reply's read snapshot.
        # With one it waits until the reply commits, so this wait is deliberately bounded.
        writer_finished.wait(0.3)

    request_engine = client.app.app.state.engine
    event.listen(request_engine, "after_cursor_execute", after_parent_read)
    try:
        reply = client.post(
            f"/api/v1/agents/messages/{letter_id}/reply",
            json={"text": "The repair is complete; please verify it."},
            headers=headers,
        )
    finally:
        event.remove(request_engine, "after_cursor_execute", after_parent_read)
        for thread in threads:
            thread.join(timeout=5)
    assert threads and writer_finished.is_set() and not writer_errors
    assert reply.status_code == 200
    assert reply.json()["in_reply_to"] == letter_id


# ------------------------------------------------- what reaches the Owner (2026-10-12)


def test_a_matter_that_is_hers_never_reaches_the_owner_and_a_tool_is_noted_for_the_developer(
    engine, staffed
):
    """The Owner, 2026-10-12, over six «Am nevoie de decizia ta» letters about a prompt that
    came back unchanged and a redo the tariff could not price: «ar trebui să nu ajungă la
    mine, este la Director!». Quality, prompts and tools are hers: the escalation becomes her
    own decision on the record, no letter goes to him, and the tool she names is written
    down for the developer in her own thread, resolved at once."""
    from app.agents.director import DEVELOPER_DEFECT_KIND, director_review

    kael = staffed["agents"]["VideoEditor"]
    with Session(engine) as session, session.begin():
        qc = post_message(
            session,
            intent="ESCALATE",
            subject="Randarea nu a trecut QC: picture_qc failed on Scene 5",
            body_text="Scena 5 arată o spirală de lumină nedorită deasupra șervetului. Kael",
            from_agent_id=kael.id,
        ).id
    registry, _ = registry_with(
        staffed,
        _decide_all(
            "ESCALATE_TO_OWNER",
            note=(
                "Owner decision needed: fix or replace the rewrite tool — the motion-prompt "
                "rewrite returned byte-identical prompts twice."
            ),
        ),
    )

    director_review(engine, registry, str(uuid4()))

    assert letters_for_owner(engine) == []
    with Session(engine) as session:
        row = session.get(AgentMessage, qc)
        assert row.status == "RESOLVED"
        assert "Decizia este a Directoarei" in (row.resolution or "")
        assert "rewrite tool" in (row.resolution or "")
        notes = [
            m
            for m in session.scalars(select(AgentMessage))
            if isinstance(m.body_json, dict) and m.body_json.get("kind") == DEVELOPER_DEFECT_KIND
        ]
        assert len(notes) == 1
        (note,) = notes
        assert note.to_agent_id == staffed["agents"]["Director"].id
        assert note.status == "RESOLVED" and note.in_reply_to == qc
        assert "byte-identical" in (note.body_text or "")
        assert open_messages(session, inbox=True) == []

    # Read again: nothing left to escalate, no second note.
    director_review(engine, registry, str(uuid4()))
    with Session(engine) as session:
        assert (
            len(
                [
                    m
                    for m in session.scalars(select(AgentMessage))
                    if isinstance(m.body_json, dict)
                    and m.body_json.get("kind") == DEVELOPER_DEFECT_KIND
                ]
            )
            == 1
        )
    assert letters_for_owner(engine) == []


def test_his_accounts_and_what_only_he_authorises_still_reach_him(engine, staffed):
    from app.agents.director import director_review

    vera = staffed["agents"]["Publisher"]
    with Session(engine) as session, session.begin():
        hold = post_message(
            session,
            intent="ESCALATE",
            subject="Publication HOLD: contul YouTube cere re-autentificare",
            body_text="Token-ul canalului B a expirat; nu pot publica. Vera",
            from_agent_id=vera.id,
        ).id
    registry, _ = registry_with(
        staffed, _decide_all("ESCALATE_TO_OWNER", note="Trebuie să te autentifici din nou.")
    )

    director_review(engine, registry, str(uuid4()))

    (letter,) = letters_for_owner(engine)
    assert letter["thread_id"] == hold and letter["for_owner"] is True
    with Session(engine) as session:
        assert session.get(AgentMessage, hold).status == "ANSWERED"
