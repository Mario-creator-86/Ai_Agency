"""Phase 1 ORM models — agent/role/capability/provider entities.

History tables (tool_receipt) are immutable via DB triggers (see migration 0002).
"""

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Role(Base):
    """A named role definition. Roles are referenced by agents."""

    __tablename__ = "role"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    mission: Mapped[str] = mapped_column(Text)
    allowed_task_types: Mapped[str] = mapped_column(Text)
    prohibited_actions: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))
    event_id: Mapped[str] = mapped_column(ForeignKey("domain_event.event_id"))


class Capability(Base):
    """A named capability that a model may or may not support."""

    __tablename__ = "capability"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text)


class RoleCapability(Base):
    """Which capabilities a role *requires*."""

    __tablename__ = "role_capability"
    __table_args__ = (UniqueConstraint("role_id", "capability_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("role.id"))
    capability_id: Mapped[str] = mapped_column(ForeignKey("capability.id"))
    requirement_level: Mapped[str] = mapped_column(String(20))


class ProviderRecord(Base):
    """A registered provider endpoint."""

    __tablename__ = "provider_record"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    provider_type: Mapped[str] = mapped_column(String(50))
    base_url: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30))
    last_health_check: Mapped[str | None] = mapped_column(String(40), nullable=True)
    adapter_version: Mapped[str] = mapped_column(String(20))
    notes: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))
    event_id: Mapped[str] = mapped_column(ForeignKey("domain_event.event_id"))


class ModelRecord(Base):
    """A known model on a provider."""

    __tablename__ = "model_record"
    __table_args__ = (UniqueConstraint("provider_id", "model_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("provider_record.id"))
    model_name: Mapped[str] = mapped_column(String(200))
    discovery_method: Mapped[str] = mapped_column(String(30))
    context_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_verified: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean)
    notes: Mapped[str] = mapped_column(Text)


class ModelCapability(Base):
    """Capability-to-model mapping."""

    __tablename__ = "model_capability"
    __table_args__ = (UniqueConstraint("model_id", "capability_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("model_record.id"))
    capability_id: Mapped[str] = mapped_column(ForeignKey("capability.id"))
    confidence: Mapped[str] = mapped_column(String(30))


class Agent(Base):
    """An agent: managed runtime identity backed by a model/provider."""

    __tablename__ = "agent"
    __table_args__ = (CheckConstraint("version >= 1"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100))
    role_id: Mapped[str] = mapped_column(ForeignKey("role.id"))
    provider_id: Mapped[str] = mapped_column(ForeignKey("provider_record.id"))
    model_id: Mapped[str] = mapped_column(ForeignKey("model_record.id"))
    lifecycle: Mapped[str] = mapped_column(String(20))
    runtime_state: Mapped[str] = mapped_column(String(25))
    cost_limit_per_task: Mapped[str | None] = mapped_column(String(20), nullable=True)
    max_concurrent_tasks: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    hired_at: Mapped[str] = mapped_column(String(40))
    terminated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("domain_event.event_id"))


class AgentRun(Base):
    """Envelope for a real LLM invocation."""

    __tablename__ = "agent_run"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent.id"))
    task_type: Mapped[str] = mapped_column(String(100))
    objective: Mapped[str] = mapped_column(Text)
    prompt_template_version: Mapped[str] = mapped_column(String(50))
    model_name: Mapped[str] = mapped_column(String(200))
    provider_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30))
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_vr: Mapped[str | None] = mapped_column(String(20), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36))
    started_at: Mapped[str] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("domain_event.event_id"), nullable=True)


class ToolReceipt(Base):
    """Immutable receipt for every real tool call. Protected by DB trigger."""

    __tablename__ = "tool_receipt"
    __table_args__ = {"sqlite_autoincrement": True}

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receipt_id: Mapped[str] = mapped_column(String(36), unique=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_run.id"))
    tool_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    request_summary: Mapped[dict] = mapped_column(JSON)
    result_summary: Mapped[dict] = mapped_column(JSON)
    remote_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cost_vr: Mapped[str | None] = mapped_column(String(20), nullable=True)
    called_at: Mapped[str] = mapped_column(String(40))
    returned_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
