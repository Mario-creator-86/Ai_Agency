"""Typed messages between employees (../architecture/20_EMPLOYEE_AGENT_SPEC.md, Communication).

An employee that lacks capability, evidence, budget or authority returns a structured blocker;
here that blocker becomes an ESCALATE message in the Director's inbox. Stage outcomes become
STATUS reports. The Director answers with REQUEST_INFO or resolves. Every message is an event,
so the office's activity log shows who asked whom for what, and the day's log can cite it.

Since migration 0027 a message is also a letter in a thread: it says who wrote to whom, when,
about what and why (`body_text`), and a reply or a forward inherits the thread, so whoever
receives it reads the whole exchange. `thread_messages` is that exchange, in order.

A letter to the Owner is said once (2026-10-12, the Owner over Sarah's cost report, sent three
times in 26 hours: «nu trebuie să se repete»): a report with the subject and the words of one
sent in the last `OWNER_REPEAT_DAYS` days is not sent again, open or closed, and a newer letter
on a subject still open replaces that letter's words instead of being dropped (`post_message`).
A letter that asks him something (`OWNER_ASKING_INTENTS`) and that he closed is a new question
when it comes back: his account signed out again, the GPU that again did not confirm its stop.
What he reads is checked against his rule for text (`wording.owner_text_problems`), and a
letter that breaks it is logged, never refused: a letter about his account must still reach
him with a code left in it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.models import MESSAGE_INTENTS, Agent, AgentMessage
from app.services import utc_now
from app.wording import owner_text_findings
from app.workflows.services import append_event_with_outbox

logger = logging.getLogger("studio.messages")

#: A report to the Owner with the subject and the words of one sent this recently is not sent
#: again, whether he closed it or not (2026-10-12: the cost report reached him three times in
#: 26 hours; once closed, the open-subject rule let the same text back in at the next review).
OWNER_REPEAT_DAYS = 7
#: The letters that ask him something (`decisions.services.ASKING_INTENTS`, his Decisions
#: window's cards). One he closed is answered; the same words again are the matter come back,
#: and the week's rule never holds them: his YouTube sign-in that expired again, the RunPod GPU
#: that again did not confirm its stop, the worker failing again. They are his by the rule of
#: 2026-10-12 (accounts, authorisations, security) and must reach him each time they happen.
OWNER_ASKING_INTENTS = frozenset({"REQUEST_INFO", "REQUEST_REVIEW", "CHALLENGE", "ESCALATE"})
#: Letters written «to the Owner» that are the Director's own matter under his rule of
#: 2026-10-12 («nu trebuie să ajungă la mine, este la Director»: only accounts, authorisations
#: and security are his; money goes through cards): a day the studio cut and resumes itself, the
#: GPU guard's own off, a film continuation or purchase the studio itself interrupted and takes
#: up again, her acceptance or refusal of pictures and films after quality control, her
#: editorial judgement of a script. 2026-10-15 19:30Z he counted fifteen open letters and one
#: real card; fourteen were these. Such a letter goes to the Director's inbox instead.
DIRECTOR_MATTER_KINDS = frozenset(
    {
        "day_interrupted",
        "runpod_gpu_guard_off",
        "film_continue_interrupted",
        "film_purchase_abandoned",
        "owner_director_qc",
        "owner_director_look",
        "factual_short",
    }
)
#: The shooting-sheet letter is his only when the film waits on HIS decision (a paid step
#: above his cap: NEEDS_APPROVAL); a film that waits on the studio's own walk is hers.
SHEET_LETTER_DIRECTOR_STATUSES = frozenset({"WAITING", "STOPPED", "SKIPPED"})


def directors_matter(body: dict[str, Any] | None) -> bool:
    """Whether a letter meant for the Owner is, by his letters rule, the Director's."""
    data = body if isinstance(body, dict) else {}
    kind = str(data.get("kind") or "")
    if kind in DIRECTOR_MATTER_KINDS:
        return True
    return kind == "owner_shooting_sheet" and str(data.get("status") or "") in (
        SHEET_LETTER_DIRECTOR_STATUSES
    )


#: The letters each of which is money that went out (`economy.accountant._letter_each_time`:
#: «none may be folded into another»): a second one with the same words is a second purchase,
#: so neither the week's rule nor a new text over the open one applies to them; they keep the
#: open-subject rule they had before 2026-10-12.
OWNER_LETTERS_EACH_TIME = frozenset(
    {"booking_refused", "paid_step_interrupted", "film_purchase_abandoned"}
)


class MessageError(ValueError):
    """A message that breaks the intent or lifecycle rules; nothing was written."""


def post_message(
    session: Session,
    *,
    intent: str,
    subject: str,
    body: dict[str, Any] | None = None,
    from_agent_id: str | None = None,
    to_agent_id: str | None = None,
    run_id: str | None = None,
    correlation_id: str | None = None,
    body_text: str | None = None,
    in_reply_to: str | None = None,
    thread_id: str | None = None,
    to_owner: bool = False,
) -> AgentMessage:
    """Write a letter. ``to_owner`` addresses it to the Owner: it is not in the Director's
    inbox, it shows in red on the page, and it waits for the Owner's own answer.

    A letter to the Owner is said once. The same subject still OPEN is that letter: with the
    same words nothing is written; with newer words (a report whose figures changed) its words
    are replaced and the change is an event, never dropped. A report (a letter that asks him
    nothing) with the subject and words of one sent in the last `OWNER_REPEAT_DAYS` days and
    closed since is not sent again; a question he closed is asked again when it comes back
    (`OWNER_ASKING_INTENTS`). Either way the letter returned is the one he reads."""
    if intent not in MESSAGE_INTENTS:
        raise MessageError(f"Unknown message intent {intent!r}")
    if to_owner and directors_matter(body):
        from app.agents.memory import agent_for_role  # noqa: PLC0415 - memory imports us

        director = agent_for_role(session, "Director")
        if director is not None:
            # His letters rule (2026-10-12): the Director's matter goes to her inbox, in
            # the same words, and never counts among what waits for him.
            to_owner = False
            to_agent_id = director.id
            body = {**dict(body or {}), "to": "Director", "redirected_from": "Owner"}
    if to_owner:
        to_agent_id = None
        body = {**dict(body or {}), "to": "Owner", "owner_attention": True}
    title = " ".join(str(subject).split())
    if not title:
        raise MessageError("A message needs a subject")
    letter = str(body_text or "").strip() or None
    if to_owner:
        each_time = str(dict(body or {}).get("kind") or "") in OWNER_LETTERS_EACH_TIME
        # One open letter per matter. The same subject already waiting for the Owner's answer
        # is that letter — one evening she was asked the same question nine times, once per
        # review, because each review found the matter still open.
        waiting = next(
            (
                row
                for row in session.scalars(
                    select(AgentMessage)
                    .where(
                        AgentMessage.status == "OPEN",
                        AgentMessage.to_agent_id.is_(None),
                        AgentMessage.subject == title,
                    )
                    .order_by(AgentMessage.created_at.desc())
                )
                if is_for_owner(row)
            ),
            None,
        )
        if waiting is not None:
            if letter and not each_time and _words(waiting.body_text) != _words(letter):
                _revise(
                    session,
                    waiting,
                    intent=intent,
                    body=body,
                    letter=letter,
                    correlation_id=correlation_id,
                )
            return waiting
        # Only a report is held by the week's rule: a question he closed was answered, and
        # the same question again is the matter come back (the review of 2026-10-12: an
        # expired sign-in or an unconfirmed GPU stop folded into last week's closed letter
        # would leave the studio waiting on him without his knowing).
        sent = (
            None
            if each_time or intent in OWNER_ASKING_INTENTS
            else repeated_letter(session, subject=title, body_text=letter, to_owner=True)
        )
        if sent is not None:
            logger.info(
                "owner_letter_not_repeated",
                extra={"message_id": sent.id, "kind": dict(body or {}).get("kind")},
            )
            return sent
        _check_owner_words(letter, body)
    parent = session.get(AgentMessage, in_reply_to) if in_reply_to else None
    if in_reply_to and parent is None:
        raise MessageError("The message being answered does not exist")
    identifier = str(uuid4())
    row = AgentMessage(
        id=identifier,
        intent=intent,
        from_agent_id=from_agent_id,
        to_agent_id=to_agent_id,
        subject=title,
        body_json=dict(body or {}),
        run_id=run_id,
        status="OPEN",
        created_at=utc_now(),
        # A reply lives in its parent's thread; a first letter starts its own.
        thread_id=thread_id or (parent.thread_id or parent.id if parent else identifier),
        in_reply_to=parent.id if parent else None,
        body_text=letter,
    )
    session.add(row)
    session.flush()
    names = {
        a.id: a.display_name
        for a in session.scalars(
            select(Agent).where(Agent.id.in_([x for x in (from_agent_id, to_agent_id) if x]))
        )
    }
    event, _ = append_event_with_outbox(
        session,
        "agent.message_posted",
        "agent_message",
        row.id,
        1,
        {
            "intent": intent,
            "subject": title,
            "from_agent_id": from_agent_id,
            "from_name": names.get(from_agent_id or ""),
            "to_agent_id": to_agent_id,
            "to_name": "Owner" if to_owner else (names.get(to_agent_id or "") or "Director"),
            "for_owner": to_owner,
            "thread_id": row.thread_id,
            "in_reply_to": row.in_reply_to,
            "excerpt": " ".join(letter.split())[:300] if letter else "",
        },
        correlation_id or str(uuid4()),
    )
    row.event_id = event.event_id
    return row


def _words(text: str | None) -> str:
    """A letter's words with its spacing set aside: what «the same words» compares."""
    return " ".join(str(text or "").split())


def repeated_letter(
    session: Session,
    *,
    subject: str,
    body_text: str | None,
    to_owner: bool = True,
    from_agent_id: str | None = None,
    kind: str | None = None,
    days: int = OWNER_REPEAT_DAYS,
) -> AgentMessage | None:
    """The newest letter with this subject and these words written in the last ``days`` days,
    open or closed, or None: a letter that would say again what was said. ``to_owner`` looks
    among the letters to the Owner; otherwise among the other letters ``from_agent_id`` wrote
    (of ``kind`` when given)."""
    title = " ".join(str(subject).split())
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    query = select(AgentMessage).where(
        AgentMessage.subject == title, AgentMessage.created_at >= since
    )
    if to_owner:
        query = query.where(AgentMessage.to_agent_id.is_(None))
    elif from_agent_id is not None:
        query = query.where(AgentMessage.from_agent_id == from_agent_id)
    words = _words(body_text)
    for row in session.scalars(query.order_by(AgentMessage.created_at.desc())):
        if to_owner != is_for_owner(row) or _words(row.body_text) != words:
            continue
        body = row.body_json if isinstance(row.body_json, dict) else {}
        if kind is not None and body.get("kind") != kind:
            continue
        return row
    return None


def _check_owner_words(letter: str | None, body: dict[str, Any] | None) -> list[str]:
    """His rule for text, read on a letter about to reach him: logged when it is broken, never
    a refusal (a letter about his account must reach him whatever its words). The composers'
    tests hold each one to it (`wording.owner_text_problems`)."""
    found = owner_text_findings(letter)
    if found:
        logger.warning(
            "owner_letter_words",
            extra={"kind": dict(body or {}).get("kind"), "problems": found},
        )
    return list(found)


def _revise(
    session: Session,
    row: AgentMessage,
    *,
    intent: str,
    body: dict[str, Any] | None,
    letter: str,
    correlation_id: str | None,
) -> None:
    """A newer letter on a subject still open for the Owner: the open letter says the newer
    words, and the change is an event (`agent.message_posted` again, ``revised``), so the
    register shows the new figures and the record keeps the old ones. Before 2026-10-12 the
    newer letter was dropped and he read the old figures until he closed it."""
    _check_owner_words(letter, body)
    before = _words(row.body_text)
    # Newer figures under a question still open leave it a question: a report's words do not
    # take the card off his Decisions window before he has answered.
    if intent in OWNER_ASKING_INTENTS or row.intent not in OWNER_ASKING_INTENTS:
        row.intent = intent
    row.body_json = dict(body or {})
    row.body_text = letter
    author = session.get(Agent, row.from_agent_id) if row.from_agent_id else None
    event, _ = append_event_with_outbox(
        session,
        "agent.message_posted",
        "agent_message",
        row.id,
        2,
        {
            "intent": intent,
            "subject": row.subject,
            "from_agent_id": row.from_agent_id,
            "from_name": author.display_name if author is not None else None,
            "to_agent_id": None,
            "to_name": "Owner",
            "for_owner": True,
            "thread_id": row.thread_id,
            "in_reply_to": row.in_reply_to,
            "excerpt": _words(letter)[:300],
            "revised": True,
            "previous_excerpt": before[:300],
        },
        correlation_id or str(uuid4()),
    )
    row.event_id = event.event_id


def forward_message(
    session: Session,
    message_id: str,
    *,
    to_agent_id: str | None,
    from_agent_id: str | None,
    note: str,
    correlation_id: str | None = None,
) -> AgentMessage:
    """Pass a letter on, with a note, inside its thread — the receiver reads the exchange."""
    original = session.get(AgentMessage, message_id)
    if original is None:
        raise MessageError("Message not found")
    return post_message(
        session,
        intent="HANDOFF",
        subject=("Fwd: " + original.subject),
        body={"forwarded_message_id": original.id, "original_intent": original.intent},
        body_text=note,
        from_agent_id=from_agent_id,
        to_agent_id=to_agent_id,
        in_reply_to=original.id,
        correlation_id=correlation_id,
    )


def thread_messages(session: Session, thread_id: str) -> list[AgentMessage]:
    """Every message of a thread, oldest first. Rows from before 0027 are their own thread."""
    return list(
        session.scalars(
            select(AgentMessage)
            .where((AgentMessage.thread_id == thread_id) | (AgentMessage.id == thread_id))
            .order_by(AgentMessage.created_at.asc())
        )
    )


def thread_view(engine: Engine, thread_id: str) -> dict[str, Any]:
    with Session(engine) as session:
        names = {a.id: a.display_name for a in session.scalars(select(Agent))}
        rows = thread_messages(session, thread_id)
        return {
            "thread_id": thread_id,
            "subject": message_view(rows[0], names)["subject"] if rows else "",
            "messages": [message_view(r, names) for r in rows],
        }


def resolve_message(
    session: Session,
    message_id: str,
    *,
    resolution: str,
    resolved_by: str,
    status: str = "RESOLVED",
    correlation_id: str | None = None,
) -> AgentMessage:
    if status not in ("ANSWERED", "RESOLVED"):
        raise MessageError("A message is answered or resolved; nothing else")
    row = session.get(AgentMessage, message_id)
    if row is None:
        raise MessageError("Message not found")
    if row.status == "RESOLVED":
        raise MessageError("Message is already resolved")
    row.status = status
    row.resolution = str(resolution).strip() or None
    row.resolved_by = resolved_by[:100]
    row.resolved_at = utc_now()
    event, _ = append_event_with_outbox(
        session,
        "agent.message_resolved" if status == "RESOLVED" else "agent.message_answered",
        "agent_message",
        row.id,
        2,
        {
            "intent": row.intent,
            "subject": row.subject,
            "resolved_by": row.resolved_by,
            # The register draws this event: an ask the studio's sweep closed with nobody's
            # answer is never «a răspuns» there (STUB-006, 2026-10-16).
            "expired": closed_unanswered(row),
        },
        correlation_id or str(uuid4()),
    )
    row.event_id = event.event_id
    return row


def is_for_owner(row: AgentMessage) -> bool:
    """A letter addressed to the Owner, not to the Director's inbox."""
    body = row.body_json if isinstance(row.body_json, dict) else {}
    return body.get("to") == "Owner"


def open_messages(
    session: Session, *, to_agent_id: str | None = None, inbox: bool = False, limit: int = 50
) -> list[AgentMessage]:
    """OPEN messages addressed to an agent, or (inbox=True) to the Director's inbox.

    A letter to the Owner shares the inbox's NULL addressee but is not the Director's to
    read: she wrote it, or an employee wrote it past her. It is left out of the inbox.
    """
    query = select(AgentMessage).where(AgentMessage.status == "OPEN")
    if inbox:
        query = query.where(AgentMessage.to_agent_id.is_(None))
        rows = session.scalars(query.order_by(AgentMessage.created_at.desc()).limit(limit * 2))
        return [r for r in rows if not is_for_owner(r)][:limit]
    if to_agent_id is not None:
        query = query.where(AgentMessage.to_agent_id == to_agent_id)
    return list(session.scalars(query.order_by(AgentMessage.created_at.desc()).limit(limit)))


def letters_for_owner(engine: Engine, *, open_only: bool = True, limit: int = 50) -> list[dict]:
    """What the studio has written to the Owner, newest first."""
    with Session(engine) as session:
        names = {a.id: a.display_name for a in session.scalars(select(Agent))}
        query = select(AgentMessage).where(AgentMessage.to_agent_id.is_(None))
        if open_only:
            query = query.where(AgentMessage.status == "OPEN")
        rows = session.scalars(query.order_by(AgentMessage.created_at.desc()).limit(limit * 4))
        return [message_view(r, names) for r in rows if is_for_owner(r)][:limit]


#: Who closes an ask the studio's sweep expires (`agents.inbox.expire_stale_asks`). The sweep
#: closes it ANSWERED, never RESOLVED — the sheet repair resolves its own report later, and a
#: RESOLVED letter cannot be resolved again — so this name is what tells such a letter from
#: one an employee answered (STUB-006, 2026-10-16: the page showed it as «răspuns»).
EXPIRED_BY = "Studioul (cereri expirate)"


def closed_unanswered(row: AgentMessage) -> bool:
    """Whether the studio's sweep closed this letter with nobody's answer (`EXPIRED_BY`)."""
    return row.status == "ANSWERED" and row.resolved_by == EXPIRED_BY


def message_view(row: AgentMessage, names: dict[str, str] | None = None) -> dict[str, Any]:
    names = names or {}
    body = row.body_json if isinstance(row.body_json, dict) else {}
    subject = row.subject
    if (
        row.intent == "STATUS"
        and body.get("kind") == "owner_director_qc"
        and body.get("outcome") == "BOUGHT_WAITING"
    ):
        subject = subject.replace(
            "așteaptă aprobarea preluării noi", "studioul verifică și continuă refacerea"
        )
    return {
        "id": row.id,
        "intent": row.intent,
        "from_agent_id": row.from_agent_id,
        "from_name": names.get(row.from_agent_id or "", None),
        "to_agent_id": row.to_agent_id,
        "to_name": (
            "Owner"
            if is_for_owner(row)
            else (names.get(row.to_agent_id or "", None) if row.to_agent_id else "Director")
        ),
        "for_owner": is_for_owner(row),
        "requires_owner_response": is_for_owner(row)
        and row.status == "OPEN"
        and (row.intent in OWNER_ASKING_INTENTS or (row.body_json or {}).get("outcome") == "ASKED"),
        "subject": subject,
        "body_json": row.body_json,
        "run_id": row.run_id,
        "status": row.status,
        # Closed by the studio's sweep, unanswered: the page says so instead of «răspuns».
        "expired": closed_unanswered(row),
        "resolution": row.resolution,
        "resolved_by": row.resolved_by,
        "created_at": row.created_at,
        "resolved_at": row.resolved_at,
        "thread_id": row.thread_id or row.id,
        "in_reply_to": row.in_reply_to,
        "body_text": row.body_text,
    }


def list_messages(
    engine: Engine, *, status: str | None = None, agent_id: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    with Session(engine) as session:
        names = {a.id: a.display_name for a in session.scalars(select(Agent))}
        query = select(AgentMessage)
        if status:
            query = query.where(AgentMessage.status == status)
        if agent_id:
            query = query.where(
                (AgentMessage.from_agent_id == agent_id) | (AgentMessage.to_agent_id == agent_id)
            )
        rows = session.scalars(query.order_by(AgentMessage.created_at.desc()).limit(limit)).all()
        return [message_view(r, names) for r in rows]
