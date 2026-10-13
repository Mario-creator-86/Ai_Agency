"""Correspondence that converges: one reply per letter, the newest letter answered, no echo.

2026-10-11, 10:50-10:53: three handoffs from the Director to the Accountant were answered
three times each in two minutes. The round answered each thread's oldest open letter — the
handoff, open because the work was not done — whenever the thread's last word was not hers,
so every letter the Director's review added, even one to Dr. Aris, made her answer the
handoff again; Dr. Aris's letter, behind it in the same thread, was never answered; her
replies answered the handoff, not the investigation, so the Director investigated again; and
each reply asked for the same rate card. What is asserted here, on a scripted model (nothing
reaches a vendor): the same shape now gives one reply from her and one from Dr. Aris, and no
second review; a quarter of an hour later she answers the newest letter, in reply to it, and
the answer to an investigation is read, not investigated again; a reply that asks for the
same thing again in the same words is not sent, the handoff is marked blocked and the
Director is told once; and the Accountant answers her mail with her books in front of her.

The adversarial review of the same day added the rest: a reply that brings news is sent even
when it still needs the same thing; needs that name nothing never block; every sender —
Owner, Director, colleague — gets an answer to their own letter, and one sender's letter is
never closed by a reply to another; a letter that came while she was writing is answered on
the next round; and an answer left for her next review is read once the hour has passed.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from app.agents.director import director_review
from app.agents.mail import correspondence_round, letters_awaiting_answer
from app.agents.messages import open_messages, post_message, thread_messages
from app.agents.models import AgentMessage, AgentRun
from app.models import DomainEvent
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_mail import staffed  # noqa: F401 - the staffed studio fixture

RATE_CARD = "Lista modelelor folosite și tariful fiecăruia pe milionul de tokeni."


class Office:
    """Every employee's model and the Director's, scripted by who is asked."""

    def __init__(self, answers):
        self.answers = answers
        self.calls: list[dict] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        system = kwargs.get("system") or ""
        who = "Director" if "director-inbox" in prompt else system
        self.calls.append({"who": who, "prompt": prompt})
        for name, answer in self.answers.items():
            if who == name or who.startswith(f"You are {name}"):
                return GenerateResult(answer(prompt), 10, 40, None)
        raise AssertionError(f"nobody scripted for {who[:40]!r}")


def office(staffed, answers):  # noqa: F811 - the fixture's value, passed on
    registry = ProviderRegistry()
    model = Office(answers)
    registry.register(staffed["provider_id"], model)
    return registry, model


def letter(reply, done=False, needs=""):
    return lambda prompt: json.dumps(
        {"reply": reply, "done": done, "needs": needs}, ensure_ascii=False
    )


def investigate(role):
    """A Director who asks the named role to investigate every letter in her inbox."""
    return lambda prompt: json.dumps(
        {
            "summary": "Cer detalii.",
            "decisions": [
                {
                    "message_id": i,
                    "action": "REQUEST_INVESTIGATION",
                    "assign_to_role": role,
                    "note": "Arată-mi cifrele.",
                }
                for i in re.findall(r'"id": "([0-9a-f-]{36})"', prompt)
            ],
        },
        ensure_ascii=False,
    )


def letters_from(engine, agent_id, thread_id):
    with Session(engine) as session:
        return [m for m in thread_messages(session, thread_id) if m.from_agent_id == agent_id]


def reviews(engine):
    with Session(engine) as session:
        return session.scalars(
            select(AgentRun).where(AgentRun.task_type == "director_review")
        ).all()


def the_handoff(engine, sarah, nadia):
    with Session(engine) as session, session.begin():
        return post_message(
            session,
            intent="HANDOFF",
            subject="Continuă: costul pe film față de ce a adus",
            body_text="Nadia, spune-mi cât a costat fiecare film publicat. Sarah",
            from_agent_id=sarah.id,
            to_agent_id=nadia.id,
        ).id


def test_the_shape_of_2026_10_11_gives_one_reply_and_the_colleague_is_answered(engine, staffed):  # noqa: F811
    sarah, nadia, aris = (
        staffed["agents"]["Director"],
        staffed["agents"]["Accountant"],
        staffed["agents"]["LeadResearcher"],
    )
    handoff = the_handoff(engine, sarah, nadia)
    registry, model = office(
        staffed,
        {
            nadia.display_name: letter("Am nevoie de lista modelelor. Nadia", needs=RATE_CARD),
            aris.display_name: letter("Nu țin analizele filmelor; le are contabilitatea. Aris"),
            "Director": investigate("Accountant"),
        },
    )

    # Round 1: she answers the handoff; her reply reaches the inbox and the Director, who
    # has not decided anything in this thread yet, reads it at once and asks her to look.
    first = correspondence_round(engine, registry)
    assert [a["message_id"] for a in first["answered"]] and first["review"]["applied"]
    with Session(engine) as session, session.begin():
        # The next review's letter to Dr. Aris, in the same thread (29053bf2 on 10-11).
        post_message(
            session,
            intent="REQUEST_INFO",
            subject="De investigat: câte vizualizări a adus fiecare film",
            body_text="Aris, ce au adus filmele publicate? Sarah",
            from_agent_id=sarah.id,
            to_agent_id=aris.id,
            in_reply_to=handoff,
        )

    # Rounds 2 and 3, a minute apart in the real case: she has just written in the thread,
    # so her new letter waits; Dr. Aris's letter, behind her handoff, is his turn and is
    # answered; his reply lands in a thread she decided in this hour and calls no review.
    second = correspondence_round(engine, registry)
    third = correspondence_round(engine, registry)
    assert len(second["answered"]) == 1 and third["answered"] == []
    assert "deferred" in second["review"]
    assert len(letters_from(engine, nadia.id, handoff)) == 1
    assert len(letters_from(engine, aris.id, handoff)) == 1
    assert len(reviews(engine)) == 1
    assert [c["who"] for c in model.calls].count("Director") == 1


def test_a_quarter_of_an_hour_later_she_answers_the_newest_letter_and_it_is_read(
    engine,
    staffed,  # noqa: F811
):
    sarah, nadia = staffed["agents"]["Director"], staffed["agents"]["Accountant"]
    handoff = the_handoff(engine, sarah, nadia)
    registry, _ = office(
        staffed,
        {
            nadia.display_name: letter("Am nevoie de lista modelelor. Nadia", needs=RATE_CARD),
            "Director": investigate("Accountant"),
        },
    )
    correspondence_round(engine, registry)
    with Session(engine) as session:
        asked = session.scalar(
            select(AgentMessage).where(
                AgentMessage.to_agent_id == nadia.id, AgentMessage.intent == "REQUEST_INFO"
            )
        )
        assert asked.subject.startswith("De investigat: Re: Continuă")
        asked_id = asked.id

    # Now with her books in hand she answers the investigation itself, with figures.
    registry, _ = office(
        staffed,
        {
            nadia.display_name: letter(
                "Filmul despre Higgs a costat 4,58 USD, estimat. Nadia", needs="Factura RunPod."
            ),
            "Director": investigate("Accountant"),
        },
    )
    later = datetime.now(UTC) + timedelta(minutes=16)
    result = correspondence_round(engine, registry, now=later)
    assert len(result["answered"]) == 1
    # The thread was decided in this hour: the reply waits for her next review.
    assert "deferred" in result["review"] and len(reviews(engine)) == 1
    with Session(engine) as session:
        reply = session.get(AgentMessage, result["answered"][0]["message_id"])
        assert reply.in_reply_to == asked_id
        assert reply.subject.startswith("Re: De investigat:")
        assert session.get(AgentMessage, asked_id).status == "ANSWERED"
        # Not done: the instruction still follows her until the work is.
        assert session.get(AgentMessage, handoff).status == "OPEN"
        reply_id = reply.id

    # Her next review reads the answer to her investigation; she does not ask again.
    director_review(engine, registry, str(uuid4()))
    with Session(engine) as session:
        read = session.get(AgentMessage, reply_id)
        assert read.status == "RESOLVED" and read.resolution.startswith("Luat la cunoștință")
        assert (
            session.scalar(
                select(AgentMessage).where(AgentMessage.subject.like("De investigat: Re: De%"))
            )
            is None
        )


def test_a_reply_asking_again_for_the_same_thing_is_not_sent_and_blocks_the_handoff(
    engine,
    staffed,  # noqa: F811
):
    sarah, nadia = staffed["agents"]["Director"], staffed["agents"]["Accountant"]
    handoff = the_handoff(engine, sarah, nadia)
    registry, model = office(
        staffed,
        {
            nadia.display_name: letter("Am nevoie de lista modelelor. Nadia", needs=RATE_CARD),
            "Director": investigate("Accountant"),
        },
    )
    correspondence_round(engine, registry)
    later = datetime.now(UTC) + timedelta(minutes=16)
    # The same request in much the same words: the same thing again.
    registry, model = office(
        staffed,
        {
            nadia.display_name: letter(
                "Am nevoie în continuare de lista modelelor. Nadia",
                needs="lista modelelor folosite și tariful fiecăruia, pe milionul de tokeni",
            ),
            "Director": investigate("Accountant"),
        },
    )

    result = correspondence_round(engine, registry, now=later)

    assert result["answered"] == [] and len(result["held"]) == 1
    [first_reply] = letters_from(engine, nadia.id, handoff)[:1]
    with Session(engine) as session:
        blocked = session.get(AgentMessage, handoff)
        assert blocked.status == "OPEN"
        assert blocked.body_json["blocked"]["needs"].startswith("lista modelelor")
        question = session.get(AgentMessage, result["held"][0]["answered"][0])
        assert question.intent == "REQUEST_INFO" and question.status == "ANSWERED"
        # The time of the earlier letter as the studio's clock read it, not UTC.
        written = (
            datetime.fromisoformat(first_reply.created_at)
            .astimezone(ZoneInfo("Europe/Bucharest"))
            .strftime("%Y-%m-%d %H:%M")
        )
        assert question.resolution.startswith(f"Același răspuns ca în scrisoarea din {written}")
        event = session.scalar(
            select(DomainEvent).where(DomainEvent.event_type == "agent.mail_repeated")
        )
        assert event is not None and event.payload["blocked"] == [handoff]
        # The Director is told, in her inbox, what still stops the work: a block nobody
        # reads is a thread gone silent while work is owed.
        [told] = [m for m in open_messages(session, inbox=True) if m.from_agent_id == nadia.id]
        assert told.id == result["held"][0]["told"] and told.intent == "STATUS"
        assert told.body_json["blocked_on"].startswith("lista modelelor")
        assert told.body_text.startswith("Nu pot continua fără: lista modelelor")
    # Nothing is owed in the thread now: the next rounds ask nobody.
    calls = len(model.calls)
    correspondence_round(engine, registry, now=later + timedelta(minutes=20))
    assert len(model.calls) == calls
    with Session(engine) as session:
        assert letters_awaiting_answer(session, now=later + timedelta(hours=2)) == []

    # She is asked again and repeats herself again: still one notice in the inbox.
    with Session(engine) as session, session.begin():
        post_message(
            session,
            intent="REQUEST_INFO",
            subject="Re: Continuă: costul pe film",
            body_text="Nadia, ai lista? Sarah",
            from_agent_id=sarah.id,
            to_agent_id=nadia.id,
            in_reply_to=handoff,
        )
    again = correspondence_round(engine, registry, now=later + timedelta(minutes=40))
    assert len(again["held"]) == 1 and again["held"][0]["told"] == told.id
    with Session(engine) as session:
        notices = [m for m in open_messages(session, inbox=True) if m.from_agent_id == nadia.id]
        assert [m.id for m in notices] == [told.id]


def test_a_new_letter_after_a_block_is_answered_and_a_new_answer_lifts_the_block(
    engine,
    staffed,  # noqa: F811
):
    sarah, nadia = staffed["agents"]["Director"], staffed["agents"]["Accountant"]
    handoff = the_handoff(engine, sarah, nadia)
    with Session(engine) as session, session.begin():
        row = session.get(AgentMessage, handoff)
        row.body_json = {**row.body_json, "blocked": {"needs": RATE_CARD}}
    with Session(engine) as session:
        assert letters_awaiting_answer(session) == []
    with Session(engine) as session, session.begin():
        newer = post_message(
            session,
            intent="REQUEST_INFO",
            subject="Re: Continuă: costul pe film",
            body_text="Prețul Ollama e pus din 5 octombrie; îl vezi în cărți. Sarah",
            from_agent_id=sarah.id,
            to_agent_id=nadia.id,
            in_reply_to=handoff,
        ).id
    with Session(engine) as session:
        assert letters_awaiting_answer(session) == [newer]
    registry, _ = office(
        staffed,
        {
            nadia.display_name: letter("Am găsit prețul; trimit costul diseară. Nadia"),
            "Director": lambda p: json.dumps({"summary": "Citit.", "decisions": []}),
        },
    )
    correspondence_round(engine, registry)
    with Session(engine) as session:
        row = session.get(AgentMessage, handoff)
        assert row.status == "OPEN" and "blocked" not in row.body_json
        assert session.get(AgentMessage, newer).status == "ANSWERED"


def test_the_accountant_answers_her_mail_with_her_books_in_front_of_her(engine, staffed):  # noqa: F811
    sarah, nadia, elena = (
        staffed["agents"]["Director"],
        staffed["agents"]["Accountant"],
        staffed["agents"]["FactChecker"],
    )
    with Session(engine) as session, session.begin():
        for addressee in (nadia, elena):
            post_message(
                session,
                intent="REQUEST_INFO",
                subject="Cât am cheltuit luna asta?",
                body_text="Spune-mi suma. Sarah",
                from_agent_id=sarah.id,
                to_agent_id=addressee.id,
            )
    registry, model = office(
        staffed,
        {
            nadia.display_name: letter("Zero USD. Nadia", done=True),
            elena.display_name: letter("Nu țin cărțile. Elena", done=True),
            "Director": lambda p: json.dumps({"summary": "Citit.", "decisions": []}),
        },
    )
    correspondence_round(engine, registry)
    books = next(
        c["prompt"] for c in model.calls if c["who"].startswith(f"You are {nadia.display_name}")
    )
    other = next(
        c["prompt"] for c in model.calls if c["who"].startswith(f"You are {elena.display_name}")
    )
    assert "unpriced_by_model" in books and '"films"' in books
    assert "do not ask anyone for a figure or a price the books already hold" in books
    assert "unpriced_by_model" not in other


def test_a_note_the_director_files_to_herself_waits_for_nobody(engine, staffed):  # noqa: F811
    """Three such notes (10-04, 10-05) stood open on her own desk: the thread's last word
    was hers, so nobody was asked; reading a thread by its newest letter keeps it so."""
    sarah = staffed["agents"]["Director"]
    with Session(engine) as session, session.begin():
        report = post_message(
            session, intent="STATUS", subject="Raportare: încheiată", from_agent_id=sarah.id
        )
        post_message(
            session,
            intent="REQUEST_INFO",
            subject="De investigat: Raportare: încheiată",
            from_agent_id=sarah.id,
            to_agent_id=sarah.id,
            in_reply_to=report.id,
        )
    with Session(engine) as session:
        assert letters_awaiting_answer(session, now=datetime.now(UTC) + timedelta(days=1)) == []


# ------------------------------------------------------------------ the review of 2026-10-11


def quiet_director(prompt):
    return json.dumps({"summary": "Citit.", "decisions": []})


def test_a_reply_that_brings_news_is_sent_even_when_it_still_needs_the_same(engine, staffed):  # noqa: F811
    sarah, nadia = staffed["agents"]["Director"], staffed["agents"]["Accountant"]
    handoff = the_handoff(engine, sarah, nadia)
    registry, _ = office(
        staffed,
        {
            nadia.display_name: letter("Am nevoie de tarife. Nadia", needs=RATE_CARD),
            "Director": quiet_director,
        },
    )
    correspondence_round(engine, registry)
    with Session(engine) as session, session.begin():
        question = post_message(
            session,
            intent="REQUEST_INFO",
            subject="Cât a costat filmul Higgs?",
            body_text="Nadia, cât a costat filmul Higgs? Sarah",
            from_agent_id=sarah.id,
            to_agent_id=nadia.id,
            in_reply_to=handoff,
        ).id
    registry, _ = office(
        staffed,
        {
            nadia.display_name: letter(
                "Filmul Higgs a costat 4,58 USD (RunPod, estimat). Nadia", needs=RATE_CARD
            ),
            "Director": quiet_director,
        },
    )

    result = correspondence_round(engine, registry, now=datetime.now(UTC) + timedelta(minutes=16))

    assert result["held"] == [] and len(result["answered"]) == 1
    with Session(engine) as session:
        reply = session.get(AgentMessage, result["answered"][0]["message_id"])
        assert reply.in_reply_to == question and "4,58 USD" in reply.body_text
        assert session.get(AgentMessage, question).status == "ANSWERED"


def test_needs_that_name_nothing_never_block_a_reply(engine, staffed):  # noqa: F811
    sarah, nadia = staffed["agents"]["Director"], staffed["agents"]["Accountant"]
    handoff = the_handoff(engine, sarah, nadia)
    registry, _ = office(
        staffed,
        {
            nadia.display_name: letter("Lucrez la costuri. Nadia", needs="Nimic."),
            "Director": quiet_director,
        },
    )
    correspondence_round(engine, registry)
    with Session(engine) as session, session.begin():
        post_message(
            session,
            intent="REQUEST_INFO",
            subject="Re: Continuă: costul pe film",
            body_text="Nadia, cum merge? Sarah",
            from_agent_id=sarah.id,
            to_agent_id=nadia.id,
            in_reply_to=handoff,
        )

    result = correspondence_round(engine, registry, now=datetime.now(UTC) + timedelta(minutes=16))

    assert result["held"] == [] and len(result["answered"]) == 1
    with Session(engine) as session:
        assert "blocked" not in session.get(AgentMessage, handoff).body_json


def the_owner_writes(session, nadia, after, text):
    return post_message(
        session,
        intent="REQUEST_INFO",
        subject="Re: Continuă: costul pe film",
        body={"from": "Owner"},
        body_text=text,
        from_agent_id=None,
        to_agent_id=nadia.id,
        in_reply_to=after,
    ).id


def the_director_writes(session, sarah, nadia, after):
    return post_message(
        session,
        intent="REQUEST_INFO",
        subject="De investigat: Re: Continuă: costul pe film",
        body_text="Nadia, arată cifrele. Sarah",
        from_agent_id=sarah.id,
        to_agent_id=nadia.id,
        in_reply_to=after,
    ).id


@pytest.mark.parametrize("owner_first", [True, False])
def test_the_owner_and_the_director_each_get_their_own_answer(engine, staffed, owner_first):  # noqa: F811
    """One sender's letter is never hidden behind another's, nor closed by a reply that goes
    to the other: the Owner's question behind a newer letter of hers was closed «Același
    răspuns…» with nothing sent to him, and a reply to him closed her open question."""
    sarah, nadia = staffed["agents"]["Director"], staffed["agents"]["Accountant"]
    handoff = the_handoff(engine, sarah, nadia)
    registry, _ = office(
        staffed,
        {
            nadia.display_name: letter("Am nevoie de tarife. Nadia", needs=RATE_CARD),
            "Director": quiet_director,
        },
    )
    reply_id = correspondence_round(engine, registry)["answered"][0]["message_id"]
    with Session(engine) as session, session.begin():
        if owner_first:
            owners = the_owner_writes(session, nadia, reply_id, "Nadia, cât am cheltuit azi?")
            directors = the_director_writes(session, sarah, nadia, reply_id)
        else:
            directors = the_director_writes(session, sarah, nadia, reply_id)
            owners = the_owner_writes(session, nadia, reply_id, "Nadia, cât am cheltuit azi?")
    # The Owner is answered at once; her letter waits for the quarter of an hour.
    with Session(engine) as session:
        assert letters_awaiting_answer(session) == [owners]
    registry, _ = office(
        staffed,
        {
            nadia.display_name: letter("Azi am cheltuit 0,12 USD. Nadia", needs=RATE_CARD),
            "Director": quiet_director,
        },
    )
    correspondence_round(engine, registry)
    with Session(engine) as session:
        to_him = [
            m
            for m in thread_messages(session, handoff)
            if m.from_agent_id == nadia.id and m.in_reply_to == owners
        ]
        assert len(to_him) == 1 and to_him[0].body_json["to"] == "Owner"
        assert session.get(AgentMessage, owners).status == "ANSWERED"
        assert session.get(AgentMessage, directors).status == "OPEN"

    later = correspondence_round(engine, registry, now=datetime.now(UTC) + timedelta(minutes=16))

    assert len(later["answered"]) == 1
    with Session(engine) as session:
        to_her = session.get(AgentMessage, later["answered"][0]["message_id"])
        assert to_her.in_reply_to == directors and to_her.to_agent_id is None
        assert "to" not in to_her.body_json
        assert session.get(AgentMessage, directors).status == "ANSWERED"


def test_a_letter_that_came_while_she_was_writing_is_answered_next(engine, staffed):  # noqa: F811
    sarah, nadia = staffed["agents"]["Director"], staffed["agents"]["Accountant"]
    handoff = the_handoff(engine, sarah, nadia)
    posted: list[str] = []

    def writes_while_she_answers(prompt):
        if not posted:
            with Session(engine) as session, session.begin():
                posted.append(the_owner_writes(session, nadia, handoff, "Nadia, soldul?"))
        return json.dumps({"reply": "Lucrez. Nadia", "done": False, "needs": ""})

    registry, _ = office(
        staffed, {nadia.display_name: writes_while_she_answers, "Director": quiet_director}
    )
    correspondence_round(engine, registry)
    with Session(engine) as session:
        assert letters_awaiting_answer(session) == posted

    correspondence_round(engine, registry)

    with Session(engine) as session:
        assert session.get(AgentMessage, posted[0]).status == "ANSWERED"


def test_an_answer_left_for_her_next_review_is_read_once_the_hour_has_passed(engine, staffed):  # noqa: F811
    sarah, nadia = staffed["agents"]["Director"], staffed["agents"]["Accountant"]
    the_handoff(engine, sarah, nadia)
    registry, _ = office(
        staffed,
        {
            nadia.display_name: letter("Am nevoie de lista modelelor. Nadia", needs=RATE_CARD),
            "Director": investigate("Accountant"),
        },
    )
    correspondence_round(engine, registry)
    registry, model = office(
        staffed,
        {
            nadia.display_name: letter("Filmul Higgs a costat 4,58 USD. Nadia", needs="Factura."),
            "Director": investigate("Accountant"),
        },
    )
    later = datetime.now(UTC) + timedelta(minutes=16)
    deferred = correspondence_round(engine, registry, now=later)
    assert "deferred" in deferred["review"]
    reply_id = deferred["answered"][0]["message_id"]
    # Within the hour nothing calls her; nothing else would before the evening.
    within = correspondence_round(engine, registry, now=later + timedelta(minutes=30))
    assert within["review"] is None

    read = correspondence_round(engine, registry, now=later + timedelta(hours=1, minutes=1))

    assert read["review"] and "deferred" not in read["review"]
    with Session(engine) as session:
        assert session.get(AgentMessage, reply_id).status == "RESOLVED"
    # Read once: the next round does not call her again for it.
    reviews_so_far = [c["who"] for c in model.calls].count("Director")
    correspondence_round(engine, registry, now=later + timedelta(hours=2))
    assert [c["who"] for c in model.calls].count("Director") == reviews_so_far


def test_two_colleagues_in_one_thread_are_answered_a_round_apart(engine, staffed):  # noqa: F811
    """Each sender gets an answer, but she still writes in a thread once a round: two letters
    answered in the same second is the burst the quarter of an hour is there to stop."""
    sarah, nadia, aris = (
        staffed["agents"]["Director"],
        staffed["agents"]["Accountant"],
        staffed["agents"]["LeadResearcher"],
    )
    the_handoff(engine, sarah, nadia)
    registry, _ = office(
        staffed,
        {
            nadia.display_name: letter("Am nevoie de tarife. Nadia", needs=RATE_CARD),
            "Director": quiet_director,
        },
    )
    reply_id = correspondence_round(engine, registry)["answered"][0]["message_id"]
    with Session(engine) as session, session.begin():
        directors = the_director_writes(session, sarah, nadia, reply_id)
        arises = post_message(
            session,
            intent="REQUEST_INFO",
            subject="Re: Continuă: costul pe film",
            body_text="Nadia, ce film a costat cel mai mult? Aris",
            from_agent_id=aris.id,
            to_agent_id=nadia.id,
            in_reply_to=reply_id,
        ).id
    registry, _ = office(
        staffed,
        {
            nadia.display_name: letter("Filmul Higgs, 4,58 USD. Nadia", needs="Factura."),
            "Director": quiet_director,
        },
    )
    later = datetime.now(UTC) + timedelta(minutes=16)

    first = correspondence_round(engine, registry, now=later)
    second = correspondence_round(engine, registry, now=later + timedelta(minutes=16))

    with Session(engine) as session:
        answered = [
            session.get(AgentMessage, a["message_id"]).in_reply_to
            for a in first["answered"] + second["answered"]
        ]
    assert answered == [directors, arises]
