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
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Studio(Base):
    __tablename__ = "studio"
    __table_args__ = (CheckConstraint("id = 1"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[str] = mapped_column(String(40))


class OwnerPolicy(Base):
    __tablename__ = "owner_policy"
    __table_args__ = (CheckConstraint("id = 1"), CheckConstraint("version >= 1"))

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    autonomy_stopped: Mapped[bool] = mapped_column(Boolean)
    #: TEST or PRODUCTION (migration 0031). The studio's own state, not a request's claim:
    #: a page cannot ask for production routing, and an experiment cannot buy a film.
    #: Declared server-side only, so an insert omits it: a studio bootstrapped against an
    #: older schema (the upgrade path a migration test walks) must not fail on a column that
    #: revision did not have, and a new studio gets TEST from the database.
    environment: Mapped[str] = mapped_column(String(20), nullable=False, server_default="TEST")
    #: MANUAL | SUPERVISED | AUTONOMOUS_CEO (migration 0043), the mode of
    #: `51_AUTONOMY_MODE_SEMANTICS`. It was a constant on the policy view — `Literal["MANUAL"]`
    #: — while the daily run walked twelve stages with no Owner approval between them, paid a
    #: vendor for shots and wrote to YouTube within the channel policy. The column carries the
    #: honest reading, AUTONOMOUS_CEO, and moves only through the Owner's versioned command.
    #: Server-side default for the same reason as `environment`: a bootstrap against an older
    #: schema must not name a column that revision never had.
    autonomy_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="AUTONOMOUS_CEO"
    )
    updated_at: Mapped[str] = mapped_column(String(40))


class ApprovalRequest(Base):
    """What a SUPERVISED studio asks the Owner before it writes where the public can see.

    The Approval object of `31_GOVERNANCE_APPROVAL_POLICY`: action, requester, risk tier,
    evidence, proposed diff, cost, reversibility, expiry, approver, result. The cost is
    nullable on purpose — a cost the studio cannot compute is None, never zero — and an
    expired request cannot be reused, so a request that has aged out is answered by a new
    one rather than by yesterday's silence.

    A request is keyed by its action **and** its subject — the specific thing it is about.
    Measured before that key existed: a SUPERVISED day asked about the cheap film first, and
    the second, dearer film reused the first film's row, so one "yes" would have covered a
    four-dollar film and a forty-dollar one. The subject is what makes the Owner's answer
    about the thing he was shown.
    """

    __tablename__ = "owner_approval_request"
    __table_args__ = (
        CheckConstraint("risk_tier IN ('T0','T1','T2','T3','T4')", name="ck_approval_tier"),
        CheckConstraint(
            "result IN ('PENDING','APPROVED','REFUSED','EXPIRED')", name="ck_approval_result"
        ),
        # The question asked most often: what is still waiting for the Owner, for this action.
        Index("ix_approval_open", "result", "action"),
        # And the question every gated act asks: what did he answer about *this* film.
        Index("ix_approval_subject", "action", "subject", "result"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action: Mapped[str] = mapped_column(String(100))
    #: The film, the storyboard, the channel — whatever identifies what is being asked
    #: about. Empty when the action is about the studio itself and not about a thing.
    subject: Mapped[str] = mapped_column(String(100), server_default="")
    risk_tier: Mapped[str] = mapped_column(String(4))
    requester: Mapped[str] = mapped_column(String(100))
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_diff: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #: USD, or None when nothing in the studio can price this action yet.
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    reversible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    expires_at: Mapped[str] = mapped_column(String(40))
    approver: Mapped[str | None] = mapped_column(String(100), nullable=True)
    result: Mapped[str] = mapped_column(String(20), server_default="PENDING")
    #: The Owner's own words when he answered, carried into what the stage then reports.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: When the studio spent this answer. An approval authorises one act: the column is what
    #: the gate reads, because a query that had to walk the ledger for every film would make
    #: the day's riskiest decision depend on event history. The ledger carries the fact too
    #: (`governance.approval_consumed`), which is the record, not the lock.
    consumed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    event_id: Mapped[str | None] = mapped_column(ForeignKey("domain_event.event_id"), nullable=True)


class DomainEvent(Base):
    __tablename__ = "domain_event"
    __table_args__ = {"sqlite_autoincrement": True}

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    event_type: Mapped[str] = mapped_column(String(100))
    timestamp: Mapped[str] = mapped_column(String(40))
    aggregate_type: Mapped[str] = mapped_column(String(50))
    aggregate_id: Mapped[str] = mapped_column(String(36))
    aggregate_version: Mapped[int] = mapped_column(Integer)
    correlation_id: Mapped[str] = mapped_column(String(36))
    causation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer)
    visibility: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON)


class CommandRecord(Base):
    __tablename__ = "command_record"

    idempotency_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    command_type: Mapped[str] = mapped_column(String(100))
    payload_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40))


class Room(Base):
    __tablename__ = "room"
    __table_args__ = (CheckConstraint("width > 0 AND height > 0"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    studio_id: Mapped[int] = mapped_column(ForeignKey("studio.id"))
    name: Mapped[str] = mapped_column(String(100))
    purpose: Mapped[str] = mapped_column(Text)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    event_id: Mapped[str] = mapped_column(ForeignKey("domain_event.event_id"))


# Register Phase 1, 2, 4, 5, 6, 7 and 11 models with Base.metadata
import app.agents.models  # noqa: F401, E402
import app.analytics.models  # noqa: F401, E402
import app.economy.models  # noqa: F401, E402
import app.factual.models  # noqa: F401, E402
import app.integrations.models  # noqa: F401, E402
import app.media.models  # noqa: F401, E402
import app.publishing.models  # noqa: F401, E402
import app.research.models  # noqa: F401, E402
import app.runbook.models  # noqa: F401, E402
import app.story.models  # noqa: F401, E402
import app.workflows.models  # noqa: F401, E402
import app.workforce.models  # noqa: F401, E402
import app.youtube.models  # noqa: F401, E402
