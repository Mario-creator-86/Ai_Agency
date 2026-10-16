"""Employee memory (../architecture/04_AGENT_SYSTEM.md §9).

A memory record is a fact the studio established, written by the service that established it
and tied to its provenance (an event, a run, an Owner decision). The model never writes memory
from its own text: an opinion becomes AGENT_OPINION only after a service validated the
structured output it came in. Records expire (TEMP_CONTEXT) or are invalidated with a reason;
they are never edited or deleted, so what an agent was told on a given day can be re-read.

Reading is scoped by role (../architecture/20_EMPLOYEE_AGENT_SPEC.md, Memory scope): each
role's contract says which classes it may read and write, and `recall()` returns only those,
studio-wide records plus the agent's own, newest first — except the prompt lessons, which
travel on a channel of their own (`LESSON_MARKER`).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import ColumnElement, Engine, and_, func, literal, or_, select
from sqlalchemy.orm import Session, aliased

from app.agents.models import MEMORY_CLASSES, Agent, AgentRun, MemoryRecord, Role
from app.models import DomainEvent
from app.services import utc_now

#: How many records `recall()` returns. Memory is a briefing, not an archive; the archive is the
#: table itself, and the ids of what was used are recorded on the run. An identity no longer
#: calls it (`agents.identity.compose_identity` reads by task, within a character budget); it
#: is the plain newest-first window, for whoever wants exactly that.
RECALL_LIMIT = 120
#: The Owner's policies: pinned in every identity, never chosen by recency (audit of
#: 2026-10-16: the Director's 120 newest rows covered 7.5 hours and none of his 16 policies).
OWNER_POLICY = "OWNER_POLICY"
#: TEMP_CONTEXT is about the current work; it should not outlive the week.
TEMP_CONTEXT_DAYS = 3
MAX_CONTENT = 600
#: The head of every prompt lesson row (`app.media.prompt_agent`, which reads and writes them).
#: A lesson is a studio-wide STRATEGY row, but it reaches a call only through
#: `prompt_lessons(scope)` in the task's own data, which gives each kind of film its own, says
#: which ones no picture has proven yet and sets the refuted ones apart. Through `recall()` it
#: reached every identity of a role that reads STRATEGY whole and raw, the unverified and the
#: other kind of film's included (audit of 2026-10-16, finding 22: the Director's prompt audit
#: was given 3 proven lessons in its data and 59 lesson rows in her memory, 56 unverified,
#: around the 2026-10-15 rule that she reads proven lessons only). So `recall()` leaves them out.
LESSON_MARKER = "prompt lesson:"


class MemoryError(ValueError):
    """A record that would break the memory rules; nothing was written."""


def _clip(text: str) -> str:
    return str(text).strip()


def remember(
    session: Session,
    *,
    memory_class: str,
    content: str,
    source_type: str,
    source_id: str | None = None,
    agent_id: str | None = None,
    event_id: str | None = None,
    ttl_days: int | None = None,
) -> MemoryRecord | None:
    """Write one memory record. Returns None when an identical live record already exists.

    `source_type` is where the fact came from: "event" (a domain event id), "run" (an agent
    run id, after its structured output was validated), "owner" (an Owner decision) or
    "system" (a runbook stage's own record).
    """
    if memory_class not in MEMORY_CLASSES:
        raise MemoryError(f"Unknown memory class {memory_class!r}")
    if source_type not in ("event", "run", "owner", "system"):
        raise MemoryError(f"Unknown memory source {source_type!r}")
    text = _clip(content)
    if not text:
        raise MemoryError("A memory record needs content")
    now = utc_now()
    duplicate = session.scalar(
        select(MemoryRecord).where(
            MemoryRecord.agent_id.is_(agent_id)
            if agent_id is None
            else MemoryRecord.agent_id == agent_id,
            MemoryRecord.memory_class == memory_class,
            MemoryRecord.content == text,
            MemoryRecord.invalidated_at.is_(None),
            or_(MemoryRecord.expires_at.is_(None), MemoryRecord.expires_at > now),
        )
    )
    if duplicate is not None:
        return None
    if ttl_days is None and memory_class == "TEMP_CONTEXT":
        ttl_days = TEMP_CONTEXT_DAYS
    expires = (datetime.now(UTC) + timedelta(days=ttl_days)).isoformat() if ttl_days else None
    row = MemoryRecord(
        id=str(uuid4()),
        agent_id=agent_id,
        memory_class=memory_class,
        content=text,
        source_type=source_type,
        source_id=source_id,
        created_at=now,
        expires_at=expires,
        invalidated_at=None,
        invalidation_reason=None,
        event_id=event_id,
    )
    session.add(row)
    session.flush()
    return row


def invalidate(session: Session, record_id: str, reason: str) -> MemoryRecord:
    row = session.get(MemoryRecord, record_id)
    if row is None:
        raise MemoryError("Memory record not found")
    if row.invalidated_at is None:
        row.invalidated_at = utc_now()
        row.invalidation_reason = _clip(reason) or "invalidated"
    return row


def readable_classes(role: Role | None) -> list[str]:
    scope = (
        role.memory_scope_json
        if role is not None and isinstance(role.memory_scope_json, dict)
        else {}
    )
    classes = scope.get("read")
    if isinstance(classes, list) and classes:
        return [c for c in classes if c in MEMORY_CLASSES]
    # A role without a contract yet reads what any employee may know: policy and history.
    return ["OWNER_POLICY", "HISTORICAL_EVENT", "TEMP_CONTEXT"]


def recall(
    session: Session, agent: Agent, role: Role | None, limit: int = RECALL_LIMIT
) -> list[MemoryRecord]:
    """The live records this agent may read: studio-wide ones and its own, newest first.

    Never a prompt lesson (`LESSON_MARKER`): those reach a call only in its task data.
    """
    classes = readable_classes(role)
    if not classes:
        return []
    return recent_memory(session, agent, classes, limit=limit)


def _readable(agent: Agent, classes: Iterable[str]) -> list[ColumnElement[bool]]:
    """What every read of an agent's memory shares: the classes asked, studio-wide rows and its
    own, live (not invalidated, not expired), and never a prompt lesson (`LESSON_MARKER`)."""
    now = utc_now()
    return [
        MemoryRecord.memory_class.in_(list(classes)),
        or_(MemoryRecord.agent_id.is_(None), MemoryRecord.agent_id == agent.id),
        MemoryRecord.invalidated_at.is_(None),
        or_(MemoryRecord.expires_at.is_(None), MemoryRecord.expires_at > now),
        # The same test `prompt_agent` reads its lesson rows by.
        MemoryRecord.content.not_like(f"{LESSON_MARKER}%"),
    ]


def recent_memory(
    session: Session, agent: Agent, classes: Sequence[str], *, limit: int
) -> list[MemoryRecord]:
    """The newest live rows of these classes this agent may read, at most ``limit``."""
    if not classes:
        return []
    return list(
        session.scalars(
            select(MemoryRecord)
            .where(*_readable(agent, classes))
            .order_by(MemoryRecord.created_at.desc())
            .limit(limit)
        ).all()
    )


def owner_policies(session: Session, agent: Agent, role: Role | None) -> list[MemoryRecord]:
    """Every live OWNER_POLICY row this role may read, newest first, all of them.

    Pinned whole in every identity (the Owner, 2026-10-16: «his rules, always»): chosen by
    recency among a role's other memory they were pushed out by a few hours of opinions."""
    if OWNER_POLICY not in readable_classes(role):
        return []
    return list(
        session.scalars(
            select(MemoryRecord)
            .where(*_readable(agent, [OWNER_POLICY]))
            .order_by(MemoryRecord.created_at.desc())
        ).all()
    )


def tied_memory(
    session: Session,
    agent: Agent,
    classes: Sequence[str],
    ids: Sequence[str],
    *,
    limit: int,
) -> list[MemoryRecord]:
    """The live rows of these classes tied to a call's subject, newest first, at most ``limit``.

    A row is tied to the subject (a storyboard, an episode, a topic, a day's log, a thread, a
    correlation: any id the caller named) when its source is one of those ids; when the run it
    came from was about the subject (that run recorded the ids as its ``subject_ids``, or ran
    under one of them as its correlation); when the event it came from is the subject's; or
    when its words name one of the ids, whole or by the eight characters the studio quotes
    them by («Chose today's topic 1c038a99»)."""
    wanted = sorted({str(i) for i in ids if str(i).strip()})
    if not classes or not wanted:
        return []
    run = aliased(AgentRun)
    event = aliased(DomainEvent)
    listed = func.json_each(run.context_json, "$.subject_ids").table_valued("value")
    recorded = select(literal(1)).select_from(listed).where(listed.c.value.in_(wanted)).exists()
    heads = sorted({i[:8] for i in wanted if len(i) >= 8})
    named = [MemoryRecord.content.contains(head, autoescape=True) for head in heads]
    return list(
        session.scalars(
            select(MemoryRecord)
            .outerjoin(
                run, and_(MemoryRecord.source_type == "run", run.id == MemoryRecord.source_id)
            )
            .outerjoin(event, event.event_id == MemoryRecord.event_id)
            .where(
                *_readable(agent, classes),
                or_(
                    MemoryRecord.source_id.in_(wanted),
                    run.correlation_id.in_(wanted),
                    event.aggregate_id.in_(wanted),
                    recorded,
                    *named,
                ),
            )
            .order_by(MemoryRecord.created_at.desc())
            .limit(limit)
        ).all()
    )


def memory_view(row: MemoryRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "memory_class": row.memory_class,
        "content": row.content,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
        "invalidated_at": row.invalidated_at,
        "invalidation_reason": row.invalidation_reason,
    }


def agent_for_role(session: Session, role_name: str) -> Agent | None:
    """The active employee holding a role, for services that remember on its behalf."""
    return session.scalar(
        select(Agent)
        .join(Role, Agent.role_id == Role.id)
        .where(Role.name == role_name, Agent.lifecycle == "ACTIVE")
        .order_by(Agent.hired_at)
    )


def list_memory(engine: Engine, agent_id: str, include_studio: bool = True) -> list[dict[str, Any]]:
    with Session(engine) as session:
        condition = (
            or_(MemoryRecord.agent_id == agent_id, MemoryRecord.agent_id.is_(None))
            if include_studio
            else MemoryRecord.agent_id == agent_id
        )
        rows = session.scalars(
            select(MemoryRecord)
            .where(condition)
            .order_by(MemoryRecord.created_at.desc())
            .limit(200)
        ).all()
        return [memory_view(r) for r in rows]
