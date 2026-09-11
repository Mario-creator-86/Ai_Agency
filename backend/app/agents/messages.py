"""Typed messages between employees (../architecture/20_EMPLOYEE_AGENT_SPEC.md, Communication).

An employee that lacks capability, evidence, budget or authority returns a structured blocker;
here that blocker becomes an ESCALATE message in the Director's inbox. Stage outcomes become
STATUS reports. The Director answers with REQUEST_INFO or resolves. Every message is an event,
so the office's activity log shows who asked whom for what, and the day's log can cite it.
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
) -> AgentMessage:
    if intent not in MESSAGE_INTENTS:
        raise MessageError(f"Unknown message intent {intent!r}")
    title = " ".join(str(subject).split())[:200]
    if not title:
        raise MessageError("A message needs a subject")
    row = AgentMessage(
        id=str(uuid4()),
        intent=intent,
        from_agent_id=from_agent_id,
        to_agent_id=to_agent_id,
        subject=title,
        body_json=dict(body or {}),
        run_id=run_id,
        status="OPEN",
        created_at=utc_now(),
    )
    session.add(row)
    session.flush()
    sender = session.get(Agent, from_agent_id) if from_agent_id else None
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
            "from_name": sender.display_name if sender else None,
            "to_agent_id": to_agent_id,
        },
        correlation_id or str(uuid4()),
    )
    row.event_id = event.event_id
    return row


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


def open_messages(
    session: Session, *, to_agent_id: str | None = None, inbox: bool = False, limit: int = 50
) -> list[AgentMessage]:
    """OPEN messages addressed to an agent, or (inbox=True) to the Director's inbox."""
    query = select(AgentMessage).where(AgentMessage.status == "OPEN")
    if inbox:
        query = query.where(AgentMessage.to_agent_id.is_(None))
    elif to_agent_id is not None:
        query = query.where(AgentMessage.to_agent_id == to_agent_id)
    return list(session.scalars(query.order_by(AgentMessage.created_at.desc()).limit(limit)))


def message_view(row: AgentMessage, names: dict[str, str] | None = None) -> dict[str, Any]:
    names = names or {}
    return {
        "id": row.id,
        "intent": row.intent,
        "from_agent_id": row.from_agent_id,
        "from_name": names.get(row.from_agent_id or "", None),
        "to_agent_id": row.to_agent_id,
        "to_name": names.get(row.to_agent_id or "", None) if row.to_agent_id else "Director",
        "subject": row.subject,
        "body_json": row.body_json,
        "run_id": row.run_id,
        "status": row.status,
        "resolution": row.resolution,
        "resolved_by": row.resolved_by,
        "created_at": row.created_at,
        "resolved_at": row.resolved_at,
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
