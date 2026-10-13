"""Phase 10 tables — what a daily run actually did, stage by stage."""

from __future__ import annotations

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class DailyRun(Base):
    """One execution of the daily runbook.

    ``status`` is never written directly by a caller: it is derived from the stages that were
    recorded, so a run cannot report success while carrying a stage that never ran. The preflight
    result is stored with it, because "the studio ran today" means something different on a day
    when half the providers were missing, and that difference has to survive in the record.
    """

    __tablename__ = "daily_run"
    __table_args__ = (
        CheckConstraint("stages_total >= 0", name="ck_daily_run_stage_count"),
        Index("ix_daily_run_started", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    business_date: Mapped[str] = mapped_column(String(10), nullable=False)
    #: READY | DEGRADED | BLOCKED, as the preflight found it — not as the run would prefer.
    preflight_status: Mapped[str] = mapped_column(String(20), nullable=False)
    preflight_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    # RUNNING | COMPLETED | PARTIAL | BLOCKED | FAILED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RUNNING")
    #: Every stage attempted, with its outcome and the reason for it.
    stages_json: Mapped[list] = mapped_column(JSON, nullable=False)
    stages_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stages_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Set when the run stopped early, naming the stage and the reason.
    stopped_at_stage: Mapped[str | None] = mapped_column(String(60), nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: TRANSIENT | HARD when the run FAILED, else NULL. A transient fault (a timeout, a
    #: provider's 5xx, "database is locked") did not open safe mode and the day may be
    #: attempted again; a hard one did, and waits for a person.
    fault_class: Mapped[str | None] = mapped_column(String(12), nullable=True)
    started_at: Mapped[str] = mapped_column(String(40), nullable=False)
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )


class SafeModeRecord(Base):
    """A period during which the studio refused to act autonomously.

    Entering safe mode is easy and leaving it is not: a P0 is cleared by a person who looked at
    it, so the exit carries a note. Without that, safe mode becomes a state the system can talk
    itself out of.
    """

    __tablename__ = "safe_mode_record"
    __table_args__ = (Index("ix_safe_mode_open", "cleared_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    #: What triggered it, for grouping: PREFLIGHT | STAGE_FAILURE | OWNER
    trigger: Mapped[str] = mapped_column(String(30), nullable=False)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("daily_run.id"), nullable=True
    )
    entered_at: Mapped[str] = mapped_column(String(40), nullable=False)
    cleared_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cleared_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )
