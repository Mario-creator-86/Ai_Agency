"""Employee memory (../architecture/04_AGENT_SYSTEM.md §9).

A memory record is a fact the studio established, written by the service that established it
and tied to its provenance (an event, a run, an Owner decision). The model never writes memory
from its own text: an opinion becomes AGENT_OPINION only after a service validated the
structured output it came in. Records expire (TEMP_CONTEXT) or are invalidated with a reason;
they are never edited or deleted, so what an agent was told on a given day can be re-read.

Reading is scoped by role (../architecture/20_EMPLOYEE_AGENT_SPEC.md, Memory scope): each
role's contract says which classes it may read and write, and `recall()` returns only those,
studio-wide records plus the agent's own, newest first.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, or_, select
from sqlalchemy.orm import Session

from app.agents.models import MEMORY_CLASSES, Agent, MemoryRecord, Role
from app.services import utc_now

#: How many records one run is given. Memory is a briefing, not an archive; the archive is the
#: table itself, and the ids of what was used are recorded on the run.
RECALL_LIMIT = 120
#: TEMP_CONTEXT is about the current work; it should not outlive the week.
TEMP_CONTEXT_DAYS = 3
MAX_CONTENT = 600


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
    """The live records this agent may read: studio-wide ones and its own, newest first."""
    classes = readable_classes(role)
    if not classes:
        return []
    now = utc_now()
    rows = session.scalars(
        select(MemoryRecord)
        .where(
            MemoryRecord.memory_class.in_(classes),
            or_(MemoryRecord.agent_id.is_(None), MemoryRecord.agent_id == agent.id),
            MemoryRecord.invalidated_at.is_(None),
            or_(MemoryRecord.expires_at.is_(None), MemoryRecord.expires_at > now),
        )
        .order_by(MemoryRecord.created_at.desc())
        .limit(limit)
    ).all()
    return list(rows)


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
