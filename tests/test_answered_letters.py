"""Letters to the Owner that ask about something no longer waiting close themselves.

2026-10-09 (film babcf272): the Owner closed six «Foaia de filmare: … așteaptă răspunsul tău la
pasul …» letters by hand, each about a question he had already answered on the sheet or a state
the film had already left. `answered_letters.retire_answered_letters` (the watchdog's pass and
the sheet letter's writer) closes them:

- a sheet letter whose question (``approval_id``) was answered, withdrawn or expired;
- a sheet letter a newer sheet letter about the same film moved past;
- the list of his standing questions once none of them waits.

A letter that reports a fact (money, books), an open question and another film's letter stay.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.agents.messages import post_message
from app.agents.models import AgentMessage
from app.media.answered_letters import retire_answered_letters
from app.models import ApprovalRequest
from app.schemas import ApprovalDecisionCommand
from app.services import decide_approval, request_approval
from sqlalchemy.orm import Session

FILM = "babcf272-0000-0000-0000-000000000001"
OTHER = "babcf272-0000-0000-0000-000000000002"


def ask(engine, storyboard_id: str = FILM, step: str = "motion") -> str:
    with Session(engine) as session, session.begin():
        return str(
            request_approval(
                session,
                "media.motion_purchase",
                "T3",
                "Video Editor",
                subject=storyboard_id,
                evidence="Mișcarea pentru restul scenelor.",
                proposed_diff={"plan_hash": "b" * 64, "step": step, "cap_credits": 176},
                cost_usd=0.88,
            ).id
        )


def letter(engine, body: dict, subject: str = "Foaia de filmare") -> str:
    with Session(engine) as session, session.begin():
        return str(
            post_message(
                session,
                intent="ESCALATE",
                subject=subject,
                body=body,
                body_text="Către Owner. Filmul așteaptă răspunsul tău.",
                to_owner=True,
            ).id
        )


#: Each letter a minute after the one before, as the day writes them (two letters in the same
#: clock tick cannot say which is newer, and are both kept).
_clock = iter(range(10_000))


def sheet_letter(engine, storyboard_id: str = FILM, **fields) -> str:
    # The real subject names the film and what it waits on; post_message keeps one letter per
    # subject, so each letter here says its own.
    subject = f"Foaia de filmare: «{storyboard_id[-1]}» {fields.get('step')} {fields.get('status')}"
    message_id = letter(
        engine,
        {"kind": "owner_shooting_sheet", "storyboard_id": storyboard_id, **fields},
        subject=subject,
    )
    with Session(engine) as session, session.begin():
        session.get(AgentMessage, message_id).created_at = (
            datetime(2026, 10, 9, 12, 0, tzinfo=UTC) + timedelta(minutes=next(_clock))
        ).isoformat()
    return message_id


def status(engine, message_id: str) -> tuple[str, str | None, str | None]:
    with Session(engine) as session:
        row = session.get(AgentMessage, message_id)
        return row.status, row.resolved_by, row.resolution


def answer(engine, approval_id: str, decision: str = "APPROVED") -> None:
    decide_approval(
        engine,
        ApprovalDecisionCommand(command_id=uuid4(), approval_id=approval_id, decision=decision),
    )


def test_a_sheet_letter_closes_once_its_question_is_answered(engine):
    approval = ask(engine)
    asking = sheet_letter(engine, approval_id=approval, step="motion", status="ASKED")

    assert retire_answered_letters(engine)["answered"] == []
    assert status(engine, asking)[0] == "OPEN"

    answer(engine, approval)
    closed = retire_answered_letters(engine)

    assert closed["answered"] == [asking]
    state, by, resolution = status(engine, asking)
    assert (state, by) == ("RESOLVED", "system")
    assert "nu mai așteaptă răspunsul tău" in resolution
    # Idempotent: a closed letter is not closed again.
    assert retire_answered_letters(engine)["answered"] == []


def test_a_refused_or_expired_question_closes_its_letter_too(engine):
    refused = ask(engine, step="stills")
    refused_letter = sheet_letter(engine, approval_id=refused, status="ASKED")
    answer(engine, refused, "REFUSED")
    expired = ask(engine, OTHER)
    with Session(engine) as session, session.begin():
        session.get(ApprovalRequest, expired).expires_at = (
            datetime.now(UTC) - timedelta(minutes=1)
        ).isoformat()
    expired_letter = sheet_letter(engine, OTHER, approval_id=expired, status="ASKED")

    closed = retire_answered_letters(engine)

    assert sorted(closed["answered"]) == sorted([refused_letter, expired_letter])
    assert "a fost retrasă sau a expirat" in status(engine, refused_letter)[2]
    assert "a fost retrasă sau a expirat" in status(engine, expired_letter)[2]


def test_a_newer_letter_about_the_same_film_moves_past_the_older_one(engine):
    busy = sheet_letter(engine, step="stills", status="FILM_BUSY")
    other_film = sheet_letter(engine, OTHER, step="stills", status="FILM_BUSY")
    hero = sheet_letter(engine, step="motion", status="HERO_NOT_APPROVED")

    closed = retire_answered_letters(engine)

    assert closed["superseded"] == [busy]
    assert status(engine, busy)[0] == "RESOLVED"
    assert status(engine, hero)[0] == "OPEN", "the film's newest word must stay"
    assert status(engine, other_film)[0] == "OPEN", "another film's letter was closed"


def test_an_open_question_keeps_its_letter_and_a_fact_is_never_closed(engine):
    approval = ask(engine)
    asking = sheet_letter(engine, approval_id=approval, status="ASKED")
    money = letter(
        engine,
        {"kind": "paid_step_interrupted", "storyboard_id": FILM},
        subject="Pasul «restul mișcării» s-a oprit după ce a plătit",
    )
    # Even a newer sheet letter does not close a letter about money.
    sheet_letter(engine, step="assemble", status="ASKED")

    retire_answered_letters(engine)

    assert status(engine, money)[0] == "OPEN"
    # The asking letter was moved past by the newer one about the same film.
    assert status(engine, asking)[0] == "RESOLVED"


def test_the_list_of_standing_questions_closes_when_none_waits(engine):
    first, second = ask(engine), ask(engine, OTHER)
    listed = letter(
        engine,
        {
            "kind": "owner_waiting",
            "questions": [{"id": first, "subject": FILM}, {"id": second, "subject": OTHER}],
            "count": 2,
        },
        subject="2 întrebări așteaptă răspunsul tău",
    )
    unreadable = letter(
        engine,
        {"kind": "owner_waiting", "questions": [{"subject": FILM}], "count": 1},
        subject="O întrebare așteaptă răspunsul tău",
    )

    answer(engine, first)
    assert retire_answered_letters(engine)["lists"] == []
    assert status(engine, listed)[0] == "OPEN", "one question still waits"

    answer(engine, second, "REFUSED")
    assert retire_answered_letters(engine)["lists"] == [listed]
    assert status(engine, listed)[0] == "RESOLVED"
    assert status(engine, unreadable)[0] == "OPEN"


def test_a_sheet_letter_closes_when_the_films_walk_left_the_state_it_named(engine):
    """2026-10-12 («The Zero Script Club», scene 6): «scena 6 așteaptă decizia Proprietarului»
    stayed OPEN after the walk moved the scene to the Director's ladder, which writes him no
    newer sheet letter to move past it; the film's newest walk says where it stands."""
    from app.services import append_event

    said = (
        "după pasul «restul mișcării», scena 6 așteaptă decizia Proprietarului pe foaia de "
        "filmare; nu se cumpără din nou până nu decide el."
    )
    asking = sheet_letter(engine, step="motion", status="NEEDS_OWNER", reason=said)
    other = sheet_letter(engine, OTHER, step="motion", status="NEEDS_OWNER", reason=said)

    def walked(film: str, state: str, reason: str) -> None:
        with Session(engine) as session, session.begin():
            append_event(
                session,
                "runbook.film_state",
                "storyboard",
                film,
                1,
                {
                    "business_date": "2026-10-12",
                    "status": state,
                    "refusal": "NEEDS_OWNER",
                    "step": "motion",
                    "reason": reason,
                    "moved": False,
                },
                str(uuid4()),
            )

    # The walk found the film where the letter said (the event's reason bare of the period).
    walked(FILM, "WAITING", said.rstrip("."))
    assert retire_answered_letters(engine)["moved_on"] == []
    assert status(engine, asking)[0] == "OPEN"

    # The walk moved the scene to the Director's ladder: the state the letter named is gone.
    hers = (
        "după pasul «restul mișcării», scena 6 refuzată de controlul calității așteaptă "
        "rescrierea Directoarei; nu se cumpără din nou până nu o rescrie ea."
    )
    walked(FILM, "WAITING", hers)
    closed = retire_answered_letters(engine)

    assert closed["moved_on"] == [asking]
    state, by, resolution = status(engine, asking)
    assert (state, by) == ("RESOLVED", "system")
    assert "a plecat din starea" in resolution and "rescrierea Directoarei" in resolution
    assert status(engine, other)[0] == "OPEN", "another film's letter was closed"
    assert retire_answered_letters(engine)["moved_on"] == []


def test_his_own_answered_letter_is_left_as_he_left_it(engine):
    approval = ask(engine)
    asking = sheet_letter(engine, approval_id=approval, status="ASKED")
    with Session(engine) as session, session.begin():
        session.get(AgentMessage, asking).status = "ANSWERED"
    answer(engine, approval)

    assert retire_answered_letters(engine)["answered"] == []
    assert status(engine, asking)[0] == "ANSWERED"
