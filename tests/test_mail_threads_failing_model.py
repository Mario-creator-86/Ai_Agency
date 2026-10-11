"""A model that refuses every call is not asked every pass, and its refusal says why.

2026-10-04, 05:23-07:51: the Accountant had been put on a model of the seeded local Ollama
endpoint that refused every call. Three letters waited for her; the round tried each about
160 times — every worker pass — 492 failed runs in two and a half hours, each recorded only
as "HTTPError": the adapter passed urllib's error on without its status, so no run said
whether a key was refused or a model was gone. What is asserted here, with the endpoint faked
at `urlopen` and the model faked at the registry (nothing reaches a vendor): the refusal is
the studio's provider error with its status and the vendor's one-word code, never its text,
and a refusal of the keyless local endpoint says to sign that service in, not to re-enter a key
it never had; a failing letter is counted and waits longer after each failure, and an employee
whose model keeps failing waits as a person — thirty letters do not mean thirty clocks — so the
same two and a half hours ask the model a handful of times; the letter's own first try never
ends its wait; and a change of model ends it.
"""

from __future__ import annotations

import asyncio
import io
import json
from datetime import UTC, datetime, timedelta
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError
from uuid import uuid4

import app.agents.services as agent_services
import pytest
from app.agents.mail import (
    ANSWER_BACKOFF_BASE_SECONDS,
    correspondence_round,
    letters_awaiting_answer,
)
from app.agents.messages import post_message
from app.agents.models import Agent, AgentMessage, AgentRun, ModelRecord
from app.integrations.llm import ProviderHTTPError
from app.providers.base import GenerateResult, HealthResult
from app.providers.ollama import OllamaProvider
from app.providers.registry import ProviderRegistry
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_mail import staffed  # noqa: F401 - the staffed studio fixture


def refusal(status: int, body: object) -> HTTPError:
    raw = json.dumps(body).encode() if not isinstance(body, bytes) else body
    return HTTPError(
        "http://127.0.0.1:11434/api/generate", status, "refused", Message(), io.BytesIO(raw)
    )


class Refusing:
    """An employee's model whose provider refuses every call."""

    def __init__(self) -> None:
        self.asked = 0

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        self.asked += 1
        raise ProviderHTTPError(401, word="unauthorized")


def letters_to(engine, staffed, count: int) -> tuple[str, list[str]]:  # noqa: F811
    sarah, nadia = staffed["agents"]["Director"], staffed["agents"]["Accountant"]
    with Session(engine) as session, session.begin():
        ids = [
            post_message(
                session,
                intent="HANDOFF",
                subject=f"Închide ziua {day}",
                body_text="Nadia, închide cărțile zilei. Sarah",
                from_agent_id=sarah.id,
                to_agent_id=nadia.id,
            ).id
            for day in range(1, count + 1)
        ]
    return nadia.id, ids


def three_letters_to(engine, staffed) -> tuple[str, list[str]]:  # noqa: F811
    return letters_to(engine, staffed, 3)


@pytest.fixture
def round_clock(monkeypatch):
    """The passes' clock, which the runs keep too, a millisecond apart: in the studio a pass
    takes its moment and the runs it makes start just after it. A test that moved the passes
    on while the runs kept the wall clock could not see a run begun after a failure."""
    clock = {"now": datetime.now(UTC), "ticks": 0}

    def run_time() -> str:
        clock["ticks"] += 1
        return (clock["now"] + timedelta(milliseconds=clock["ticks"])).isoformat()

    monkeypatch.setattr(agent_services, "utc_now", run_time)
    return clock


def passes(engine, registry, model, clock, minutes: int) -> int:
    """One pass a minute, as the worker came round on 2026-10-04; how many passes asked."""
    start, asking = clock["now"], 0
    for minute in range(minutes):
        clock["now"] = start + timedelta(minutes=minute)
        before = model.asked
        correspondence_round(engine, registry, now=clock["now"])
        asking += model.asked > before
    return asking


# ------------------------------------------------------------------ the adapter's refusal


@pytest.mark.parametrize(
    ("status", "body", "word"),
    [
        (401, {"error": "unauthorized"}, "unauthorized"),
        (
            403,
            {
                "error": {
                    "code": 403,
                    "message": "API key AIzaFAKEKEY1234 invalid",
                    "status": "PERMISSION_DENIED",
                }
            },
            "PERMISSION_DENIED",
        ),
        (404, {"error": "model 'glm-5.3-flash:cloud' not found, key sk-FAKE1234"}, None),
        (401, b"<html>nope</html>", None),
    ],
)
def test_a_refused_generation_carries_its_status_and_only_the_vendors_word(status, body, word):
    provider = OllamaProvider()
    with patch("app.providers.ollama.urlopen", side_effect=refusal(status, body)):
        with pytest.raises(ProviderHTTPError) as raised:
            asyncio.run(provider.generate("glm-5.3-flash:cloud", "Închide ziua."))
    error = raised.value
    assert error.http_status == status and error.word == word
    shown = f"{error} {error.word} {error.__cause__} {error.__context__}"
    assert "AIza" not in shown and "sk-FAKE" not in shown and "127.0.0.1" not in shown


def test_the_run_records_the_status_so_the_owner_knows_what_to_fix(engine, staffed):  # noqa: F811
    nadia, _ = three_letters_to(engine, staffed)
    registry = ProviderRegistry()
    registry.register(staffed["provider_id"], OllamaProvider())

    def refuse(*args, **kwargs):
        raise refusal(401, {"error": "unauthorized"})  # a fresh refusal, body and all, per call

    with patch("app.providers.ollama.urlopen", side_effect=refuse):
        result = correspondence_round(engine, registry)

    assert len(result["refused"]) == 3 and result["refused"][0]["attempt"] == 1
    with Session(engine) as session:
        runs = session.scalars(select(AgentRun).where(AgentRun.agent_id == nadia)).all()
        assert runs and {r.status for r in runs} == {"FAILED"}
        # The seeded endpoint is called with no key: there is none in Settings to re-enter.
        assert {r.error_detail for r in runs} == {
            "ProviderHTTPError: HTTP 401 (unauthorized) — serviciul local nu este autentificat "
            "la contul furnizorului (nu are cheie în Setări); autentifică-l sau mută angajatul "
            "pe un model al unei conexiuni verificate"
        }


def test_a_refusal_of_a_key_the_studio_sent_still_asks_for_the_key(engine, staffed):  # noqa: F811
    three_letters_to(engine, staffed)
    registry = ProviderRegistry()
    registry.register(staffed["provider_id"], OllamaProvider(api_key="test-key-not-real"))

    def refuse(*args, **kwargs):
        raise refusal(401, {"error": "unauthorized"})

    with patch("app.providers.ollama.urlopen", side_effect=refuse):
        correspondence_round(engine, registry)
    with Session(engine) as session:
        details = {r.error_detail for r in session.scalars(select(AgentRun))}
    assert details == {
        "ProviderHTTPError: HTTP 401 (unauthorized) — cheia conexiunii este respinsă "
        "(expirată, revocată sau greșită); reintrodu cheia"
    }


# ------------------------------------------------------------------ the back-off


def test_a_failing_models_letters_back_off_instead_of_being_asked_every_pass(
    engine,
    staffed,  # noqa: F811
    round_clock,
):
    nadia, letters = three_letters_to(engine, staffed)
    model = Refusing()
    registry = ProviderRegistry()
    registry.register(staffed["provider_id"], model)
    start = round_clock["now"]

    first = correspondence_round(engine, registry, now=start)

    assert model.asked == 3 and len(first["refused"]) == 3
    with Session(engine) as session:
        attempts = session.get(AgentMessage, letters[0]).body_json["answer_attempts"]
        assert attempts["count"] == 1 and attempts["error"].startswith(f"{nadia} did not answer")
        assert datetime.fromisoformat(attempts["retry_after"]) == start + timedelta(
            seconds=ANSWER_BACKOFF_BASE_SECONDS
        )
    # The next pass, half a minute later, asks nobody.
    round_clock["now"] = start + timedelta(seconds=30)
    correspondence_round(engine, registry, now=round_clock["now"])
    assert model.asked == 3

    # The rest of the morning of 2026-10-04, one pass a minute: 147 more passes.
    round_clock["now"] = start + timedelta(minutes=1)
    passes(engine, registry, model, round_clock, 147)

    # 492 runs then; seven now, at 0 (three), 6, 17, 38 and 79 minutes: her wait doubles
    # after each failed try, and each try is one letter of hers, not all three.
    assert model.asked == 7, model.asked
    with Session(engine) as session:
        counts = [
            session.get(AgentMessage, m).body_json["answer_attempts"]["count"] for m in letters
        ]
        assert sum(counts) == model.asked, counts
        assert all(session.get(AgentMessage, m).status == "OPEN" for m in letters)


def test_thirty_letters_to_a_failing_model_do_not_mean_thirty_clocks(
    engine,
    staffed,  # noqa: F811
    round_clock,
):
    """Kept per letter, the wait let a refusing model be asked on 135 passes of 148 with 30
    letters open (Marcus had 53 open handoffs on 10-11): each letter's clock ran out in turn."""
    letters_to(engine, staffed, 30)
    model = Refusing()
    registry = ProviderRegistry()
    registry.register(staffed["provider_id"], model)

    asking = passes(engine, registry, model, round_clock, 148)

    # The first pass tries a round's worth (six letters); then she waits as one person, and
    # is tried with one letter at 41 and at 122 minutes.
    assert asking == 3 and model.asked == 8, (asking, model.asked)


class NarratesThenRefusedThinking(Refusing):
    """A model that narrates instead of the schema, then refuses the second try's native
    thinking (HTTP 400: «does not support thinking»): the letter's first run SUCCEEDED, its
    second FAILED."""

    async def generate(self, model, prompt, **kwargs):
        self.asked += 1
        if (kwargs.get("extra") or {}).get("think"):
            raise ProviderHTTPError(400)
        return GenerateResult("Let me look at the books first, then I will answer.", 10, 40, None)


def test_the_letters_own_first_try_does_not_end_its_wait(engine, staffed, round_clock):  # noqa: F811
    """The wait was stamped with the pass's moment, and the letter's own first try, begun just
    after it, read as «a success since»: the letter was retried on 31 passes of 31."""
    _, [letter] = letters_to(engine, staffed, 1)
    model = NarratesThenRefusedThinking()
    registry = ProviderRegistry()
    registry.register(staffed["provider_id"], model)

    asking = passes(engine, registry, model, round_clock, 31)

    # Tries at 0, 5 and 15 minutes; the next wait (20 minutes) runs past the half hour.
    assert asking == 3, asking
    with Session(engine) as session:
        attempts = session.get(AgentMessage, letter).body_json["answer_attempts"]
        assert attempts["count"] == asking and attempts["run_status"] == "FAILED"


def test_a_change_of_model_ends_the_wait(engine, staffed):  # noqa: F811
    nadia, letters = three_letters_to(engine, staffed)
    registry = ProviderRegistry()
    registry.register(staffed["provider_id"], Refusing())
    start = datetime.now(UTC)
    correspondence_round(engine, registry, now=start)
    with Session(engine) as session:
        assert letters_awaiting_answer(session, now=start + timedelta(minutes=1)) == []

    # The Owner (or a repair) puts her on another model: the failures were the old model's.
    with Session(engine) as session, session.begin():
        agent = session.get(Agent, nadia)
        other = ModelRecord(
            id=str(uuid4()),
            provider_id=agent.provider_id,
            model_name="mistral-large-4",
            discovery_method="MANUAL",
            is_available=True,
            notes="",
        )
        session.add(other)
        session.flush()
        agent.model_id = other.id
    with Session(engine) as session:
        assert letters_awaiting_answer(session, now=start + timedelta(minutes=1)) == letters


class Silent(Refusing):
    """A model that answers with nothing: the letter's own failure, not the provider's."""

    async def generate(self, model, prompt, **kwargs):
        self.asked += 1
        return GenerateResult("", 10, 0, None)


@pytest.mark.parametrize(("model", "waits"), [(Refusing, False), (Silent, True)])
def test_a_run_that_succeeds_since_ends_a_providers_wait_not_the_letters(
    engine,
    staffed,  # noqa: F811
    model,
    waits,
):
    nadia, letters = three_letters_to(engine, staffed)
    registry = ProviderRegistry()
    registry.register(staffed["provider_id"], model())
    start = datetime.now(UTC)
    correspondence_round(engine, registry, now=start)

    # Her model answers again, on another task (the key was renewed, the outage ended).
    with Session(engine) as session, session.begin():
        tried = session.scalars(select(AgentRun).where(AgentRun.agent_id == nadia)).first()
        session.add(
            AgentRun(
                id=str(uuid4()),
                agent_id=nadia,
                task_type="reconcile_day",
                objective="închide ziua",
                prompt_template_version="accountant-v1",
                model_name=tried.model_name,
                provider_name=tried.provider_name,
                status="SUCCEEDED",
                output_text="{}",
                correlation_id=str(uuid4()),
                started_at=(datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
                context_json={},
            )
        )
    with Session(engine) as session:
        waiting = letters_awaiting_answer(session, now=start + timedelta(minutes=1))
    # A refused call waited for the provider, which answers again; an empty answer was the
    # letter's own, and another task's success says nothing about it.
    assert waiting == ([] if waits else letters)
