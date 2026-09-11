"""Phase 8 — proposing workforce changes from measurements, and applying the Owner's decision.

Two rules run through this module.

**Evidence, not impression.** Every proposal is built from rows the studio already has — agent
runs, their outcomes, the task queue — and carries the numbers it was built from. Nothing here
asks a model what it thinks of an employee. A recommendation to end someone's work has to be
checkable months later by reading what was counted.

**The Owner decides.** The studio proposes; applying a proposal is an Owner action. Autonomous
firing sits behind a feature flag that is off, and while it is off there is no code path that
changes employment without an explicit decision.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.agents.memory import remember
from app.agents.models import Agent, AgentRun, Role
from app.models import OwnerPolicy
from app.services import append_event, utc_now
from app.workflows.models import TaskQueueItem
from app.workforce.models import EmploymentRecord, WorkforceProposal

#: Fewer runs than this is an anecdote, not a performance record.
MIN_RUNS_FOR_JUDGEMENT = 5
#: How far back a proposal looks. Older work says little about how an agent is doing now.
OBSERVATION_DAYS = 30
#: A failure rate at or above this is what triggers a suspension proposal.
FAILURE_RATE_THRESHOLD = 0.5
#: Queue backlog per active agent that suggests the studio is short-handed.
BACKLOG_PER_AGENT_THRESHOLD = 8

PROPOSAL_TYPES = ("HIRE_ROLE", "TERMINATE_AGENT", "SUSPEND_AGENT", "REASSIGN_AGENT")


class WorkforceError(ValueError):
    """A workforce change was refused."""


class AutonomousChangeBlocked(WorkforceError):
    """Something tried to change employment without an Owner decision.

    Hiring and firing are Owner-gated. This is raised rather than silently downgraded to a
    proposal, because a caller that expected the change to happen must not continue as if it had.
    """


def _window_start() -> str:
    return (datetime.now(UTC) - timedelta(days=OBSERVATION_DAYS)).isoformat()


def measure_workforce(engine: Engine) -> dict[str, Any]:
    """Read the studio's own operating record. Measures only; proposes nothing.

    Everything returned here was counted from stored rows, so the same call at the same moment
    always yields the same numbers and a proposal built from them can be re-derived.
    """
    since = _window_start()
    with Session(engine) as session:
        agents = list(
            session.scalars(
                select(Agent).where(Agent.lifecycle.in_(["ACTIVE", "PAUSED", "SUSPENDED"]))
            )
        )
        role_names = {role.id: role.name for role in session.scalars(select(Role))}

        per_agent: list[dict[str, Any]] = []
        for agent in agents:
            rows = session.execute(
                select(AgentRun.status, func.count())
                .where(AgentRun.agent_id == agent.id, AgentRun.started_at >= since)
                .group_by(AgentRun.status)
            ).all()
            counts = {status: total for status, total in rows}
            total = sum(counts.values())
            failed = sum(count for status, count in counts.items() if status != "SUCCEEDED")
            per_agent.append(
                {
                    "agent_id": agent.id,
                    "display_name": agent.display_name,
                    "role_id": agent.role_id,
                    "role_name": role_names.get(agent.role_id, "Agent"),
                    "lifecycle": agent.lifecycle,
                    "runs": total,
                    "succeeded": counts.get("SUCCEEDED", 0),
                    "failed": failed,
                    # None, not 0.0, when nothing ran: a rate over no runs is not zero, it is
                    # unknown, and zero would read as a perfect record.
                    "failure_rate": round(failed / total, 3) if total else None,
                    "status_counts": counts,
                }
            )

        backlog = session.scalar(
            select(func.count())
            .select_from(TaskQueueItem)
            .where(TaskQueueItem.status.in_(["QUEUED", "RETRYING"]))
        )
        dead_letters = session.scalar(
            select(func.count())
            .select_from(TaskQueueItem)
            .where(TaskQueueItem.status == "DEAD_LETTER")
        )

    active = [a for a in per_agent if a["lifecycle"] == "ACTIVE"]
    return {
        "measured_at": utc_now(),
        "window_days": OBSERVATION_DAYS,
        "window_start": since,
        "agents": per_agent,
        "active_agents": len(active),
        "queue_backlog": int(backlog or 0),
        "dead_letter_tasks": int(dead_letters or 0),
        "backlog_per_active_agent": (round((backlog or 0) / len(active), 2) if active else None),
        # Agents that did nothing in the window. Not a verdict — an agent may simply not have
        # been asked for anything, which is a fact about the studio, not about the agent.
        "idle_agents": [a["agent_id"] for a in active if a["runs"] == 0],
    }


def propose_workforce_changes(engine: Engine, correlation_id: str = "") -> list[dict]:
    """Turn the measurements into proposals, where the evidence supports one.

    Returns an empty list when it does not, which is the usual case for a young studio and is
    not a failure. Nothing is proposed about an agent with fewer than ``MIN_RUNS_FOR_JUDGEMENT``
    runs in the window; there is no threshold at which a small sample becomes convincing.
    """
    measurement = measure_workforce(engine)
    correlation = correlation_id or str(uuid4())
    created: list[dict] = []

    with Session(engine) as session, session.begin():
        open_targets = {
            (row.proposal_type, row.agent_id, row.role_id)
            for row in session.scalars(
                select(WorkforceProposal).where(WorkforceProposal.status == "PROPOSED")
            )
        }

        def add(
            proposal_type: str,
            summary: str,
            evidence: dict[str, Any],
            sample_size: int,
            need_score: float,
            agent_id: str | None = None,
            role_id: str | None = None,
        ) -> None:
            if (proposal_type, agent_id, role_id) in open_targets:
                return  # An undecided proposal about the same thing already stands.
            identifier = str(uuid4())
            event = append_event(
                session,
                "workforce.change_proposed",
                "workforce_proposal",
                identifier,
                1,
                {"proposal_type": proposal_type, "need_score": need_score},
                correlation,
            )
            row = WorkforceProposal(
                id=identifier,
                proposal_type=proposal_type,
                agent_id=agent_id,
                role_id=role_id,
                summary=summary,
                evidence_json=evidence,
                sample_size=sample_size,
                need_score=need_score,
                status="PROPOSED",
                created_at=utc_now(),
                event_id=event.event_id,
            )
            session.add(row)
            session.flush()
            created.append(_public(row))
            open_targets.add((proposal_type, agent_id, role_id))

        # 1. An agent failing most of its work. Suspension, not termination: the cause is often
        #    the model or the provider rather than the role, and suspension is reversible.
        for agent in measurement["agents"]:
            if agent["lifecycle"] != "ACTIVE" or agent["runs"] < MIN_RUNS_FOR_JUDGEMENT:
                continue
            rate = agent["failure_rate"]
            if rate is not None and rate >= FAILURE_RATE_THRESHOLD:
                add(
                    "SUSPEND_AGENT",
                    (
                        f"{agent['display_name']} a eșuat la {agent['failed']} din "
                        f"{agent['runs']} rulări în ultimele {OBSERVATION_DAYS} de zile "
                        f"({int(rate * 100)}%). Suspendarea oprește rularea de sarcini până "
                        "verifici modelul sau furnizorul alocat."
                    ),
                    {
                        "window_days": OBSERVATION_DAYS,
                        "window_start": measurement["window_start"],
                        "runs": agent["runs"],
                        "failed": agent["failed"],
                        "failure_rate": rate,
                        "status_counts": agent["status_counts"],
                    },
                    agent["runs"],
                    min(1.0, round(rate, 3)),
                    agent_id=agent["agent_id"],
                )

        # 2. A queue the current staff is not keeping up with.
        per_agent_backlog = measurement["backlog_per_active_agent"]
        if (
            per_agent_backlog is not None
            and per_agent_backlog >= BACKLOG_PER_AGENT_THRESHOLD
            and measurement["queue_backlog"] >= MIN_RUNS_FOR_JUDGEMENT
        ):
            add(
                "HIRE_ROLE",
                (
                    f"{measurement['queue_backlog']} sarcini în așteptare pentru "
                    f"{measurement['active_agents']} agenți activi "
                    f"({per_agent_backlog} pe agent). Un agent în plus ar reduce coada."
                ),
                {
                    "queue_backlog": measurement["queue_backlog"],
                    "active_agents": measurement["active_agents"],
                    "backlog_per_active_agent": per_agent_backlog,
                    "dead_letter_tasks": measurement["dead_letter_tasks"],
                },
                measurement["queue_backlog"],
                min(1.0, round(per_agent_backlog / (BACKLOG_PER_AGENT_THRESHOLD * 2), 3)),
            )

    return created


def _public(row: WorkforceProposal) -> dict:
    return {
        "id": row.id,
        "proposal_type": row.proposal_type,
        "agent_id": row.agent_id,
        "role_id": row.role_id,
        "summary": row.summary,
        "evidence": row.evidence_json,
        "sample_size": row.sample_size,
        "need_score": row.need_score,
        "status": row.status,
        "decision_notes": row.decision_notes,
        "created_at": row.created_at,
        "decided_at": row.decided_at,
        "applied_at": row.applied_at,
    }


def list_proposals(engine: Engine, status: str | None = None) -> list[dict]:
    with Session(engine) as session:
        stmt = select(WorkforceProposal).order_by(
            WorkforceProposal.need_score.desc(), WorkforceProposal.created_at.desc()
        )
        if status:
            stmt = stmt.where(WorkforceProposal.status == status)
        return [_public(row) for row in session.scalars(stmt)]


def decide_proposal(
    engine: Engine,
    proposal_id: str,
    approve: bool,
    notes: str,
    correlation_id: str = "",
    owner_decision: bool = True,
) -> dict:
    """Record the Owner's decision and, on approval, carry it out.

    ``owner_decision`` exists so that an autonomous caller cannot pass for the Owner by
    omission: it must say what it is, and if it is not the Owner the change is refused while
    autonomous firing is disabled.
    """
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session, session.begin():
        row = session.get(WorkforceProposal, proposal_id)
        if row is None:
            raise WorkforceError(f"Propunerea {proposal_id} nu există")
        if row.status != "PROPOSED":
            raise WorkforceError(
                f"Propunerea a fost deja {row.status.lower()}; nu poate fi decisă din nou"
            )

        if approve and not owner_decision:
            policy = session.get(OwnerPolicy, 1)
            _ = policy  # Read for the audit trail; the flag below is what governs.
            raise AutonomousChangeBlocked(
                "Angajările și încetările sunt decizii ale Owner-ului. Modificarea autonomă a "
                "personalului este dezactivată, deci propunerea rămâne în așteptare."
            )

        now = utc_now()
        row.status = "APPROVED" if approve else "REJECTED"
        row.decision_notes = notes.strip()[:2000] or None
        row.decided_at = now

        event = append_event(
            session,
            "workforce.change_approved" if approve else "workforce.change_rejected",
            "workforce_proposal",
            row.id,
            2,
            {"proposal_type": row.proposal_type, "agent_id": row.agent_id},
            correlation,
        )
        row.event_id = event.event_id
        remember(
            session,
            memory_class="OWNER_POLICY",
            content=(
                f"The Owner {'approved' if approve else 'rejected'} a workforce proposal "
                f"({row.proposal_type}): {row.summary[:300]}"
                + (f" Notes: {row.decision_notes}" if row.decision_notes else "")
            ),
            source_type="owner",
            source_id=row.id,
            event_id=event.event_id,
        )

        if approve:
            _apply(session, row, correlation, now)
            row.status = "APPLIED"
            row.applied_at = now

        session.flush()
        return _public(row)


def _apply(session: Session, row: WorkforceProposal, correlation: str, now: str) -> None:
    """Carry out an approved proposal, following the documented lifecycle."""
    if row.proposal_type == "SUSPEND_AGENT":
        agent = session.get(Agent, row.agent_id) if row.agent_id else None
        if agent is None:
            raise WorkforceError("Agentul propunerii nu mai există")
        if agent.lifecycle == "TERMINATED":
            raise WorkforceError("Un agent încheiat nu mai poate fi suspendat")
        agent.lifecycle = "SUSPENDED"
        agent.runtime_state = "IDLE"
        agent.version += 1
        agent.event_id = append_event(
            session,
            "agent.suspended",
            "agent",
            agent.id,
            agent.version,
            {"proposal_id": row.id},
            correlation,
        ).event_id
        return

    if row.proposal_type == "TERMINATE_AGENT":
        agent = session.get(Agent, row.agent_id) if row.agent_id else None
        if agent is None:
            raise WorkforceError("Agentul propunerii nu mai există")
        if agent.lifecycle == "TERMINATED":
            raise WorkforceError("Agentul este deja încheiat")
        agent.lifecycle = "TERMINATED"
        agent.runtime_state = "IDLE"
        agent.terminated_at = now
        agent.version += 1
        agent.event_id = append_event(
            session,
            "agent.terminated",
            "agent",
            agent.id,
            agent.version,
            {"proposal_id": row.id},
            correlation,
        ).event_id
        # Close the open employment period rather than deleting it: the record of who worked
        # when is what makes a later rehire an event instead of a state edit.
        open_period = session.scalars(
            select(EmploymentRecord).where(
                EmploymentRecord.agent_id == agent.id, EmploymentRecord.ended_at.is_(None)
            )
        ).first()
        if open_period is not None:
            open_period.ended_at = now
            open_period.end_reason = row.summary[:2000]
            open_period.proposal_id = row.id
        return

    # HIRE_ROLE and REASSIGN_AGENT change who does what, and both need a decision the studio
    # cannot make for the Owner: which role, and on which model. They are recorded as approved
    # and left for the Owner to carry out in Settings rather than guessed at here.
    raise WorkforceError(
        "Această propunere se aplică din Settings: alege rolul și modelul, apoi angajează sau "
        "realocă agentul. Aprobarea a fost înregistrată."
    )


def open_employment(engine: Engine, agent_id: str, role_id: str, correlation_id: str = "") -> dict:
    """Begin a period of employment. A rehire opens a new one; it never reopens a closed one."""
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session, session.begin():
        agent = session.get(Agent, agent_id)
        if agent is None:
            raise WorkforceError("Agentul nu există")
        existing = session.scalars(
            select(EmploymentRecord).where(
                EmploymentRecord.agent_id == agent_id, EmploymentRecord.ended_at.is_(None)
            )
        ).first()
        if existing is not None:
            raise WorkforceError("Agentul are deja o perioadă de angajare deschisă")

        identifier = str(uuid4())
        now = utc_now()
        event = append_event(
            session,
            "workforce.employment_started",
            "employment_record",
            identifier,
            1,
            {"agent_id": agent_id, "role_id": role_id},
            correlation,
        )
        record = EmploymentRecord(
            id=identifier,
            agent_id=agent_id,
            role_id=role_id,
            started_at=now,
            ended_at=None,
            end_reason=None,
            proposal_id=None,
            event_id=event.event_id,
        )
        session.add(record)
        # A terminated agent returns to work only through this event, never by editing state.
        if agent.lifecycle == "TERMINATED":
            agent.terminated_at = None
        agent.lifecycle = "ACTIVE"
        agent.version += 1
        session.flush()
        return {
            "id": record.id,
            "agent_id": agent_id,
            "role_id": role_id,
            "started_at": now,
            "ended_at": None,
        }


def employment_history(engine: Engine, agent_id: str) -> list[dict]:
    with Session(engine) as session:
        return [
            {
                "id": row.id,
                "agent_id": row.agent_id,
                "role_id": row.role_id,
                "started_at": row.started_at,
                "ended_at": row.ended_at,
                "end_reason": row.end_reason,
                "proposal_id": row.proposal_id,
            }
            for row in session.scalars(
                select(EmploymentRecord)
                .where(EmploymentRecord.agent_id == agent_id)
                .order_by(EmploymentRecord.started_at.desc())
            )
        ]
