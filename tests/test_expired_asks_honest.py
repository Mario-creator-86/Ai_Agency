"""An ask the studio closes unanswered says so (the audit of 2026-10-16, STUB-006 / SAFE-002).

The sweep of stale asks (`agents.inbox`) closes an ask with status ANSWERED, because the sheet
repair resolves its own report later and a RESOLVED letter cannot be resolved again. Two things
it said were not so:

- the page showed such a letter as «răspuns» (answered) — a letter nobody replied to. The
  letter now carries ``expired`` (closed by the studio's sweep), and the page reads it;
- an ask an employee's model tried to answer and failed (``answer_attempts`` on the letter)
  was closed after three days with the same words as one nobody tried, and the failure was
  erased. It is now closed as never answered, with the tries and the last failure named.

No model is called.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.agents.inbox import (
    ANSWER_FAILED,
    EXPIRED,
    EXPIRED_EVENT,
    STALE_ASK_DAYS,
    expire_stale_asks,
)
from app.agents.mail import note_failed_answer
from app.agents.messages import message_view, post_message, resolve_message
from app.agents.models import AgentMessage
from app.models import DomainEvent
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_context_profiles import (
    ago,
    staffed,  # noqa: F401 - the fixture
)


def _old_ask(engine, staffed, subject: str) -> str:  # noqa: F811 - the fixture's value
    sarah, marcus = staffed["agents"]["Director"], staffed["agents"]["ScriptWriter"]
    with Session(engine) as session, session.begin():
        row = post_message(
            session,
            intent="REQUEST_INFO",
            subject=subject,
            body={},
            body_text=f"{subject}?",
            from_agent_id=sarah.id,
            to_agent_id=marcus.id,
        )
        row.created_at = ago(days=STALE_ASK_DAYS + 2)
        return row.id


def test_an_ask_whose_answers_failed_is_closed_as_never_answered(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
):
    failed = _old_ask(engine, staffed, "Which hook works")
    quiet = _old_ask(engine, staffed, "Which title works")
    for _try in range(3):
        note_failed_answer(
            engine,
            failed,
            "the model's context window was exceeded",
            run_status="FAILED",
            now=datetime.now(UTC),
        )

    result = expire_stale_asks(engine)

    assert result["by_reason"] == {ANSWER_FAILED: 1, EXPIRED: 1}
    with Session(engine) as session:
        row = session.get(AgentMessage, failed)
        assert row.status == "ANSWERED"  # never RESOLVED: the sheet repair may still resolve it
        assert row.resolution.startswith("Închisă de studio fără răspuns:")
        assert "3 încercări" in row.resolution
        assert "nu a reușit să răspundă" in row.resolution
        assert "the model's context window was exceeded" in row.resolution
        event = session.scalar(
            select(DomainEvent).where(
                DomainEvent.event_type == EXPIRED_EVENT, DomainEvent.aggregate_id == failed
            )
        )
        assert event.payload["reason"] == ANSWER_FAILED
        assert event.payload["answer_attempts"] == 3
        assert event.payload["run_status"] == "FAILED"
        # The ask nobody tried keeps the words it had.
        other = session.get(AgentMessage, quiet)
        assert "fără să țină de un film în lucru" in other.resolution
        assert "fără răspuns" not in other.resolution


def test_a_letter_the_sweep_closed_is_shown_as_closed_unanswered_not_as_answered(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
):
    expired = _old_ask(engine, staffed, "An ask nobody needs")
    answered = _old_ask(engine, staffed, "An ask Marcus answered")
    with Session(engine) as session, session.begin():
        resolve_message(
            session,
            answered,
            resolution="Here is the answer.",
            resolved_by="Marcus (ScriptWriter)",
            status="ANSWERED",
        )
    expire_stale_asks(engine)

    with Session(engine) as session:
        assert message_view(session.get(AgentMessage, expired), {})["expired"] is True
        assert message_view(session.get(AgentMessage, answered), {})["expired"] is False
        # The sheet repair resolves its own report later, as before: then it is resolved, not
        # expired.
    with Session(engine) as session, session.begin():
        resolve_message(
            session,
            expired,
            resolution="The sheet is clean.",
            resolved_by="verificarea foii",
            correlation_id=str(uuid4()),
        )
    with Session(engine) as session:
        view = message_view(session.get(AgentMessage, expired), {})
        assert view["status"] == "RESOLVED" and view["expired"] is False


def test_the_answer_event_of_an_ask_the_sweep_closed_says_it_was_closed_unanswered(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
):
    """The register and the live window draw the event, not the letter's view (the review of
    2026-10-16): the event of an expired ask carries ``expired``, and the day's story calls it
    closed unanswered, never «a letter was answered»."""
    from app.story.projection import describe_public  # noqa: PLC0415

    expired = _old_ask(engine, staffed, "An ask nobody needs")
    answered = _old_ask(engine, staffed, "An ask Marcus answered")
    with Session(engine) as session, session.begin():
        resolve_message(
            session,
            answered,
            resolution="Here is the answer.",
            resolved_by="Marcus (ScriptWriter)",
            status="ANSWERED",
        )
    expire_stale_asks(engine)

    with Session(engine) as session:

        def answer_event(message_id: str) -> dict:
            event = session.scalar(
                select(DomainEvent).where(
                    DomainEvent.event_type == "agent.message_answered",
                    DomainEvent.aggregate_id == message_id,
                )
            )
            return dict(event.payload)

        closed, replied = answer_event(expired), answer_event(answered)
    assert closed["expired"] is True and replied["expired"] is False
    assert describe_public("agent.message_answered", closed) == "an ask was closed unanswered"
    assert describe_public("agent.message_answered", replied) == "a letter was answered"
    # An event recorded before the flag existed is read by its closer.
    older = {key: value for key, value in closed.items() if key != "expired"}
    assert describe_public("agent.message_answered", older) == "an ask was closed unanswered"
