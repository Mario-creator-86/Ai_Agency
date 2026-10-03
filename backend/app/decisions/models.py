"""The Owner's decision card (migration 0054)."""

from __future__ import annotations

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

#: Every state a card may be in. PENDING waits for his answer; WAITING_FOR_OWNER_ACTION is an
#: accepted guided card that waits for his own act (a reconnection, a file, a form at Google);
#: the other four are closed and stay in his history.
DECISION_STATUSES: tuple[str, ...] = (
    "PENDING",
    "ACCEPTED",
    "REFUSED",
    "WAITING_FOR_OWNER_ACTION",
    "WITHDRAWN",
    "EXPIRED",
)
#: The states that still wait for him; one card per dedupe key may be in them.
OPEN_STATUSES: tuple[str, ...] = ("PENDING", "WAITING_FOR_OWNER_ACTION")


class OwnerDecision(Base):
    """One question only the Owner answers, as a card in his own window.

    An agent, a stage or the audit PROPOSES it (`app.decisions.services.propose_owner_decision`);
    only "owner" decides it (`decide_owner_decision`), once, against its ``version``. His accept
    applies the chosen option through his own existing command (the budget, the paid-media rule,
    the environment, the autonomy mode) or, for a guided option, records his choice and the
    place to go and waits for his act. ``clears_when`` names the condition that makes the card
    unnecessary (the connection works again): a PENDING card is then withdrawn, a waiting one
    is completed.
    """

    __tablename__ = "owner_decision"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','ACCEPTED','REFUSED','WAITING_FOR_OWNER_ACTION',"
            "'WITHDRAWN','EXPIRED')",
            name="ck_owner_decision_status",
        ),
        CheckConstraint("version >= 1", name="ck_owner_decision_version"),
        Index("ix_owner_decision_status", "status", "created_at"),
        Index(
            "uq_owner_decision_open_key",
            "dedupe_key",
            unique=True,
            sqlite_where=text("status IN ('PENDING','WAITING_FOR_OWNER_ACTION')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    #: What the question is about, as a code: daily_budget, reconnect_connection, ...
    kind: Mapped[str] = mapped_column(String(60))
    #: The thing it is about, when it is about one: a connection, a channel, a storyboard.
    subject_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title_ro: Mapped[str] = mapped_column(String(300))
    why_ro: Mapped[str] = mapped_column(Text)
    #: The cost or the effect of deciding, in his words.
    effect_ro: Mapped[str] = mapped_column(Text)
    #: [{key, label_ro, effect_ro, recommended, apply: {type, ...}}], the recommended first.
    options: Mapped[list] = mapped_column(JSON)
    #: {type, ...}: the condition that makes the card unnecessary; None when only he closes it.
    clears_when: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #: Who proposed it: "audit", "agent:<id>", "stage:<name>".
    source: Mapped[str] = mapped_column(String(100))
    dedupe_key: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), server_default="PENDING")
    chosen_option: Mapped[str | None] = mapped_column(String(60), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decided_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: What his answer did: the command's result, the place to go, why it closed.
    applied: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #: Why the last accept could not be applied; the card stays PENDING.
    apply_error_ro: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
    #: The ledger event of the card's last transition.
    event_id: Mapped[str | None] = mapped_column(ForeignKey("domain_event.event_id"), nullable=True)
