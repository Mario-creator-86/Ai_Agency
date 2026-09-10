"""Phase 8 tables: what the studio proposes about its own staff, and why."""

from __future__ import annotations

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class WorkforceProposal(Base):
    """A proposed change to the workforce, with the measurements behind it.

    The evidence is stored, not just the conclusion. A proposal read six weeks later has to be
    checkable — how many runs it looked at, over what window, what the failure rate was — because
    "the Director recommended it" is not a reason anyone can audit.
    """

    __tablename__ = "workforce_proposal"
    __table_args__ = (
        # A proposal about an agent's performance that looked at fewer runs than this is an
        # anecdote. The service refuses to build one; the schema refuses to store one.
        CheckConstraint("sample_size >= 5", name="ck_proposal_has_evidence"),
        CheckConstraint(
            "need_score >= 0 AND need_score <= 1", name="ck_proposal_need_is_a_fraction"
        ),
        Index("ix_workforce_proposal_status", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # HIRE_ROLE | TERMINATE_AGENT | SUSPEND_AGENT | REASSIGN_AGENT
    proposal_type: Mapped[str] = mapped_column(String(30), nullable=False)
    #: The agent this concerns, when it concerns one. HIRE_ROLE names a role instead.
    agent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agent.id"), nullable=True)
    role_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("role.id"), nullable=True)
    #: What the change would achieve, in one sentence, in the Owner's language.
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    #: The measurements this rests on, exactly as they were read.
    evidence_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    #: 0..1. Not a probability — a normalised urgency, defined by the thresholds in services.py.
    need_score: Mapped[float] = mapped_column(nullable=False)
    # PROPOSED | APPROVED | REJECTED | APPLIED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PROPOSED")
    #: Free text the Owner leaves when deciding; kept so a decision is explicable later.
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    decided_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    applied_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )


class EmploymentRecord(Base):
    """One period of employment for one agent.

    `../architecture/47_STATE_MACHINE_SPECIFICATIONS.md` requires that TERMINATED cannot become
    ACTIVE by editing state, and that a rehire is an explicit employment event. That is only
    enforceable if employment is a record in its own right: a rehire opens a new row rather than
    reviving the closed one, so the history of who worked when survives, and a terminated agent
    cannot be quietly restored by flipping a column.
    """

    __tablename__ = "employment_record"
    __table_args__ = (Index("ix_employment_agent", "agent_id", "ended_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent.id"), nullable=False)
    role_id: Mapped[str] = mapped_column(String(36), ForeignKey("role.id"), nullable=False)
    started_at: Mapped[str] = mapped_column(String(40), nullable=False)
    ended_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Why this period ended. NULL while it is open.
    end_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The proposal that opened or closed it, when a proposal did.
    proposal_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workforce_proposal.id"), nullable=True
    )
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )
