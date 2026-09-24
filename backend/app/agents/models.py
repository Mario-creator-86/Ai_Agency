"""Phase 1 ORM models — agent/role/capability/provider entities.

History tables (tool_receipt) are immutable via DB triggers (see migration 0002).
"""

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
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
    #: What the role watches for, investigates, corrects, lets pass, never lets pass and
    #: escalates; who it reports to; which runbook stages it owns. Data, seeded from
    #: config/role_contracts.json, editable by the Owner, read into every run's identity.
    work_contract_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: {"read": [memory classes], "write": [memory classes]} — the role's memory scope.
    memory_scope_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    contract_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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
    #: Optional second and third models this employee may think with (migration 0034), from
    #: the same registry the primary comes from. Which model sits in which slot is the
    #: Owner's configuration; no code decides anything by a model's name.
    #: Both hold a `model_record.id`. Declared without a foreign key because SQLite cannot
    #: add one to this table by ALTER; the command that sets a slot checks the model exists,
    #: is available and satisfies what the role requires.
    secondary_model_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tertiary_model_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    #: SINGLE | FALLBACK | REVIEW | DEBATE | PARALLEL. SINGLE is how ordinary work is done.
    multi_llm_strategy: Mapped[str] = mapped_column(String(20), default="SINGLE")
    #: IMPORTANT_ONLY | LOW_CONFIDENCE | ALWAYS | MANUAL — when the extra models are worth
    #: their tokens, with the two thresholds that decide it.
    additional_llm_policy: Mapped[str] = mapped_column(String(20), default="IMPORTANT_ONLY")
    min_importance: Mapped[str] = mapped_column(String(20), default="STRATEGIC")
    min_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
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
    #: Each employee's newest run, for the snapshot's «last task» (migration 0046): one grouped
    #: MAX(started_at) per agent, read from the index rather than the table.
    #: And by start alone (migration 0047): the day's spend and tokens, live and as of a moment.
    __table_args__ = (
        Index("ix_agent_run_agent_started", "agent_id", "started_at"),
        Index("ix_agent_run_started", "started_at"),
    )

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
    #: Context manifest (04_AGENT_SYSTEM §16): identity version, contract and bible versions,
    #: memory record ids the run was given. What the model knew, recorded with what it said.
    context_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class LlmCollaboration(Base):
    """One multi-model execution, and who played which part (migration 0034).

    Each participating call is an ordinary `AgentRun` with its own model recorded, so history
    stays true when the Owner changes a slot tomorrow. This row is what joins them: the
    strategy, why a second model was called at all, what each was asked to be, whether they
    disagreed, and which answer the agent finally gave. For a Director's decision it is the
    difference between "the studio decided" and "here is what was considered".
    """

    __tablename__ = "llm_collaboration"
    __table_args__ = (
        CheckConstraint(
            "strategy IN ('SINGLE','FALLBACK','REVIEW','DEBATE','PARALLEL')",
            name="ck_collaboration_strategy",
        ),
        CheckConstraint(
            "outcome IN ('COMPLETE','PARTIAL','REVIEW_INCOMPLETE')",
            name="ck_collaboration_outcome",
        ),
        Index("ix_llm_collaboration_agent", "agent_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent.id"))
    task_type: Mapped[str] = mapped_column(String(100))
    strategy: Mapped[str] = mapped_column(String(20))
    importance: Mapped[str] = mapped_column(String(20), default="ROUTINE")
    reason: Mapped[str] = mapped_column(Text)
    primary_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_run.id"), nullable=True)
    secondary_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_run.id"), nullable=True)
    tertiary_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_run.id"), nullable=True)
    final_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_run.id"), nullable=True)
    roles_json: Mapped[dict] = mapped_column(JSON, default=dict)
    disagreed: Mapped[bool] = mapped_column(Boolean, default=False)
    disagreement_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), default="COMPLETE")
    final_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[str] = mapped_column(String(40))
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


MEMORY_CLASSES = (
    "VERIFIED_FACT",
    "STRATEGY",
    "OWNER_POLICY",
    "HISTORICAL_EVENT",
    "AGENT_OPINION",
    "TEMP_CONTEXT",
)
MESSAGE_INTENTS = ("REQUEST_INFO", "REQUEST_REVIEW", "CHALLENGE", "HANDOFF", "STATUS", "ESCALATE")
MESSAGE_STATUSES = ("OPEN", "ANSWERED", "RESOLVED")


class MemoryRecord(Base):
    """One remembered fact (04_AGENT_SYSTEM §9).

    `agent_id` NULL means studio-wide (a verified fact, an Owner policy, a strategy); set, it
    is one employee's own memory (an opinion, an event they were part of). Records are written
    by backend services from real outcomes with their provenance, never from a model's free
    text, and are invalidated rather than deleted.
    """

    __tablename__ = "memory_record"
    __table_args__ = (
        Index("ix_memory_record_agent_class", "agent_id", "memory_class", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agent.id"), nullable=True)
    memory_class: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    expires_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    invalidated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    invalidation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("domain_event.event_id"), nullable=True)


class AgentMessage(Base):
    """A typed message between employees (20_EMPLOYEE_AGENT_SPEC, Communication).

    `to_agent_id` NULL is the Director's inbox: escalations and status reports land there and
    the Director's review answers them. Free-form chatter is not stored; intents are.
    """

    __tablename__ = "agent_message"
    __table_args__ = (
        Index("ix_agent_message_status", "status", "to_agent_id"),
        Index("ix_agent_message_thread", "thread_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    intent: Mapped[str] = mapped_column(String(20), nullable=False)
    from_agent_id: Mapped[str | None] = mapped_column(ForeignKey("agent.id"), nullable=True)
    to_agent_id: Mapped[str | None] = mapped_column(ForeignKey("agent.id"), nullable=True)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_run.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    resolved_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("domain_event.event_id"), nullable=True)
    #: Correspondence (migration 0027): the thread this message belongs to — the first
    #: message's id, inherited by replies and forwards — the message it answers, and the
    #: letter as written beside the structured body.
    thread_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    in_reply_to: Mapped[str | None] = mapped_column(ForeignKey("agent_message.id"), nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
