"""Phase 2 ORM models: workflows, steps, task queue, scheduler, and transactional outbox."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Workflow(Base):
    """A durable workflow instance that tracks pipeline stage progress."""

    __tablename__ = "workflow"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    # CREATED | PREFLIGHT | ADMITTED | RUNNING | PAUSED | COMPLETED | BLOCKED
    # CANCEL_REQUESTED | CANCELLED | FAILED | NEEDS_REPAIR
    status: Mapped[str] = mapped_column(String(30))
    current_stage: Mapped[str] = mapped_column(String(50))
    config: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
    event_id: Mapped[str] = mapped_column(ForeignKey("domain_event.event_id"))


class WorkflowStep(Base):
    """An individual execution step/stage within a workflow."""

    __tablename__ = "workflow_step"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflow.id"))
    stage: Mapped[str] = mapped_column(String(50))
    # PENDING | RUNNING | COMPLETED | FAILED | BLOCKED | SKIPPED
    status: Mapped[str] = mapped_column(String(30))
    assigned_agent_id: Mapped[str | None] = mapped_column(ForeignKey("agent.id"), nullable=True)
    inputs: Mapped[dict] = mapped_column(JSON)
    outputs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("domain_event.event_id"), nullable=True)


class TaskQueueItem(Base):
    """A durable task in the execution queue with lease-based locking and retry/backoff."""

    __tablename__ = "task_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str | None] = mapped_column(ForeignKey("workflow.id"), nullable=True)
    step_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_step.id"), nullable=True)
    task_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSON)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    # QUEUED | CLAIMED | RUNNING | COMPLETED | FAILED | RETRYING | DEAD_LETTER
    status: Mapped[str] = mapped_column(String(30))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    backoff_seconds: Mapped[int] = mapped_column(Integer, default=5)
    next_attempt_at: Mapped[str] = mapped_column(String(40))
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class ScheduledJob(Base):
    """A recurring or scheduled workflow trigger with singleton-safe leader leasing."""

    __tablename__ = "scheduled_job"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    workflow_type: Mapped[str] = mapped_column(String(50))
    interval_seconds: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    next_run_at: Mapped[str] = mapped_column(String(40))
    # SKIP | CATCH_UP
    missed_policy: Mapped[str] = mapped_column(String(20), default="SKIP")
    leader_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    leader_expires_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))


class OutboxRecord(Base):
    """Transactional outbox record committed atomically with domain events."""

    __tablename__ = "outbox_record"
    __table_args__ = {"sqlite_autoincrement": True}

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(36), unique=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("domain_event.event_id"))
    destination: Mapped[str] = mapped_column(String(50), default="WEBSOCKET")
    # PENDING | PUBLISHED | FAILED
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40))
    published_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
