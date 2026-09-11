"""Typed messages between employees (../architecture/20_EMPLOYEE_AGENT_SPEC.md, Communication).

An employee that lacks capability, evidence, budget or authority returns a structured blocker;
here that blocker becomes an ESCALATE message in the Director's inbox. Stage outcomes become
STATUS reports. The Director answers with REQUEST_INFO or resolves. Every message is an event,
so the office's activity log shows who asked whom for what, and the day's log can cite it.

Since migration 0027 a message is also a letter in a thread: it says who wrote to whom, when,
about what and why (`body_text`), and a reply or a forward inherits the thread, so whoever
receives it reads the whole exchange. `thread_messages` is that exchange, in order.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.models import MESSAGE_INTENTS, Agent, AgentMessage
from app.services import utc_now
from app.workflows.services import append_event_with_outbox


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
    inbox, it shows in red on the page, and it waits for the Owner's own answer."""
    if intent not in MESSAGE_INTENTS:
        raise MessageError(f"Unknown message intent {intent!r}")
    if to_owner:
        to_agent_id = None
        body = {**dict(body or {}), "to": "Owner", "owner_attention": True}
    title = " ".join(str(subject).split())[:200]
    if not title:
        raise MessageError("A message needs a subject")
    parent = session.get(AgentMessage, in_reply_to) if in_reply_to else None
    if in_reply_to and parent is None:
        raise MessageError("The message being answered does not exist")
    identifier = str(uuid4())
    letter = str(body_text or "").strip()[:8000] or None
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
        subject=("Fwd: " + original.subject)[:200],
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
            "subject": rows[0].subject if rows else "",
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
    row.resolution = " ".join(str(resolution).split())[:2000] or None
    row.resolved_by = resolved_by[:100]
    row.resolved_at = utc_now()
    event, _ = append_event_with_outbox(
        session,
        "agent.message_resolved" if status == "RESOLVED" else "agent.message_answered",
        "agent_message",
        row.id,
        2,
        {"intent": row.intent, "subject": row.subject, "resolved_by": row.resolved_by},
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


def message_view(row: AgentMessage, names: dict[str, str] | None = None) -> dict[str, Any]:
    names = names or {}
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
        "subject": row.subject,
        "body_json": row.body_json,
        "run_id": row.run_id,
        "status": row.status,
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
