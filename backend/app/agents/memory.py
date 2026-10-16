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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import ColumnElement, Engine, and_, func, literal, or_, select
from sqlalchemy.orm import Session, aliased

from app.agents.models import MEMORY_CLASSES, Agent, AgentRun, MemoryRecord, Role
from app.models import DomainEvent, OwnerPolicy
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


#: The Owner's standing policies, one matter each, by the event his command writes beside the
#: row (`app.services`: the environment, the autonomy stop, the autonomy mode, when a paid step
#: asks him). A newer command on a matter replaces the older rule on it.
POLICY_MATTERS: dict[str, str] = {
    "owner.environment_changed": "environment",
    "autonomy.stopped": "autonomy_stop",
    "autonomy.stop_cleared": "autonomy_stop",
    "owner.autonomy_mode_changed": "autonomy_mode",
    "owner.paid_media_approval_changed": "paid_media_approval",
}
#: The Owner's decisions on one thing — an episode (`story.services`), a character's identity
#: (`media.production_policy`), a workforce proposal (`workforce.services`) — by their event.
#: They are decisions, not standing rules: they reach the calls whose subject they are about
#: (`tied_memory`) and the Owner's own chat, never every call.
DECISION_EVENT_PREFIXES = ("story.episode_", "character.identity_change_", "workforce.change_")

#: How an OWNER_POLICY row is used (`owner_policy_rows`).
POLICY_IN_FORCE = "IN_FORCE"  # the current rule on its matter: pinned in every identity
POLICY_SUPERSEDED = "SUPERSEDED"  # a rule a newer command on its matter replaced: never told
POLICY_DECISION = "DECISION"  # a decision on one thing: told where its subject is


@dataclass(frozen=True)
class PolicyRow:
    """One live OWNER_POLICY row and how it is used.

    ``set_at`` is when the Owner last set what the row says: the newest command on its matter
    that set this state. `remember` keeps one live row per text, so when he switches back to an
    earlier rule no new row is written and the old row keeps its old time; its command's time
    is the true one. A row with no command behind it keeps its own time."""

    row: MemoryRecord
    use: str
    matter: str | None
    set_at: str
    why: str


def _event_state(event_type: str, payload: Any) -> Any:
    """What a policy command set on its matter, in the shape `_policy_state` reads it."""
    data = payload if isinstance(payload, dict) else {}
    matter = POLICY_MATTERS.get(event_type)
    if matter == "environment":
        return data.get("environment")
    if matter == "autonomy_stop":
        return event_type == "autonomy.stopped"
    if matter == "autonomy_mode":
        return data.get("autonomy_mode")
    if matter == "paid_media_approval":
        kind = data.get("paid_media_approval")
        usd = data.get("over_usd")
        return (kind, float(usd) if kind == "OVER_USD" and usd is not None else None)
    return None


def _policy_state(policy: OwnerPolicy) -> dict[str, Any]:
    """The studio's policy now (`owner_policy`, the row the gates read), per matter."""
    usd = policy.paid_media_approval_over_usd
    return {
        "environment": policy.environment,
        "autonomy_stop": bool(policy.autonomy_stopped),
        "autonomy_mode": policy.autonomy_mode,
        "paid_media_approval": (
            policy.paid_media_approval,
            float(usd) if policy.paid_media_approval == "OVER_USD" and usd is not None else None,
        ),
    }


def classify_owner_policies(session: Session, rows: Sequence[MemoryRecord]) -> list[PolicyRow]:
    """Each OWNER_POLICY row with its use: the current rule on each matter IN_FORCE, the rules a
    newer command replaced SUPERSEDED, the Owner's decisions on one thing DECISION. Selection
    only: no row is changed, invalidated or deleted (they are his).

    The current rule on a matter is what the `owner_policy` row says now — the state every gate
    reads — or, without that row, what the newest command on the matter set. Of the rows that
    say it, the newest is in force. A row no known command wrote is his rule all the same, and
    is in force. Returns the rows in force first (newest set first), then the others."""
    rows = list(rows)
    events = {
        event.event_id: event
        for event in session.scalars(
            select(DomainEvent).where(
                DomainEvent.event_id.in_([r.event_id for r in rows if r.event_id])
            )
        )
    }
    commands = list(
        session.scalars(
            select(DomainEvent)
            .where(DomainEvent.event_type.in_(list(POLICY_MATTERS)))
            .order_by(DomainEvent.sequence.desc())
        )
    )
    policy = session.get(OwnerPolicy, 1)
    current: dict[str, Any] = _policy_state(policy) if policy is not None else {}
    for command in commands:  # newest first: without the row, the newest command decides
        current.setdefault(
            POLICY_MATTERS[command.event_type], _event_state(command.event_type, command.payload)
        )
    set_at: dict[str, str] = {}
    for command in commands:
        name = POLICY_MATTERS[command.event_type]
        state = _event_state(command.event_type, command.payload)
        if name not in set_at and state == current.get(name):
            set_at[name] = str(command.timestamp)
    out: list[PolicyRow] = []
    chosen: set[str] = set()
    for row in sorted(rows, key=lambda r: str(r.created_at), reverse=True):
        event = events.get(str(row.event_id or ""))
        kind = str(event.event_type) if event is not None else ""
        when = str(row.created_at)
        matter = POLICY_MATTERS.get(kind)
        if matter is None or event is None:
            if kind.startswith(DECISION_EVENT_PREFIXES):
                out.append(PolicyRow(row, POLICY_DECISION, None, when, kind))
            else:
                out.append(
                    PolicyRow(row, POLICY_IN_FORCE, None, when, "no command names its matter")
                )
            continue
        now = current.get(matter)
        if _event_state(kind, event.payload) != now:
            out.append(PolicyRow(row, POLICY_SUPERSEDED, matter, when, f"{matter} is now {now!r}"))
        elif matter in chosen:
            out.append(
                PolicyRow(row, POLICY_SUPERSEDED, matter, when, "a newer row says the same rule")
            )
        else:
            chosen.add(matter)
            out.append(
                PolicyRow(row, POLICY_IN_FORCE, matter, set_at.get(matter, when), f"the {matter}")
            )
    in_force = sorted(
        (p for p in out if p.use == POLICY_IN_FORCE), key=lambda p: p.set_at, reverse=True
    )
    return in_force + [p for p in out if p.use != POLICY_IN_FORCE]


def owner_policy_rows(session: Session, agent: Agent, role: Role | None) -> list[PolicyRow]:
    """Every live OWNER_POLICY row this role may read, classified (`classify_owner_policies`)."""
    if OWNER_POLICY not in readable_classes(role):
        return []
    return classify_owner_policies(
        session,
        session.scalars(
            select(MemoryRecord)
            .where(*_readable(agent, [OWNER_POLICY]))
            .order_by(MemoryRecord.created_at.desc())
        ).all(),
    )


def owner_policies(session: Session, agent: Agent, role: Role | None) -> list[MemoryRecord]:
    """The Owner's policies in force that this role may read: the current rule on each matter,
    newest set first, all of them.

    Pinned whole in every identity (the Owner, 2026-10-16: «his rules, always»): chosen by
    recency among a role's other memory they were pushed out by a few hours of opinions. A
    rule a newer command replaced is not told — told as «in force» beside the newer one, the
    stop he cleared and the TEST he left were read as the studio's state (2026-10-16) — and a
    decision on one thing is told only where that thing is the work (`owner_policy_rows`)."""
    return [p.row for p in owner_policy_rows(session, agent, role) if p.use == POLICY_IN_FORCE]


#: The head of the AGENT_OPINION row the Director's daily review writes on her own memory
#: (`agents.director.director_review`): her summary and her priorities for the next day.
DAILY_REVIEW_MARKER = "Daily review:"


def own_review(session: Session, agent: Agent) -> MemoryRecord | None:
    """The employee's own newest live daily review row («Daily review: … Priorities: …»), or
    None. Its priorities for the next day are written for her next decisions; read by recency
    among her other memory they were left to chance, and by her decisions' memory class
    (STRATEGY) never (2026-10-16)."""
    return session.scalar(
        select(MemoryRecord)
        .where(
            *_readable(agent, ["AGENT_OPINION"]),
            MemoryRecord.agent_id == agent.id,
            MemoryRecord.content.like(f"{DAILY_REVIEW_MARKER}%"),
        )
        .order_by(MemoryRecord.created_at.desc())
        .limit(1)
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
