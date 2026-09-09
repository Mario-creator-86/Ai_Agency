"""Phase 4 SQLAlchemy declarative models for Factual Intelligence."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class TopicIdea(Base):
    __tablename__ = "topic_idea"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    angle: Mapped[str] = mapped_column(Text, nullable=False)
    target_audience: Mapped[str] = mapped_column(String(100), nullable=False, default="general")
    novelty_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PROPOSED")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    selected_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )

    sources: Mapped[list[SourceSnapshot]] = relationship("SourceSnapshot", back_populates="topic")
    claims: Mapped[list[FactualClaim]] = relationship("FactualClaim", back_populates="topic")
    scripts: Mapped[list[ScriptDraft]] = relationship("ScriptDraft", back_populates="topic")


class SourceSnapshot(Base):
    __tablename__ = "source_snapshot"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    topic_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("topic_idea.id"), nullable=True
    )
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    publisher: Mapped[str] = mapped_column(String(200), nullable=False)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    sanitized_content: Mapped[str] = mapped_column(Text, nullable=False)
    credibility_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    fetched_at: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )

    topic: Mapped[TopicIdea | None] = relationship("TopicIdea", back_populates="sources")
    claims: Mapped[list[FactualClaim]] = relationship("FactualClaim", back_populates="source")


class FactualClaim(Base):
    __tablename__ = "factual_claim"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_snapshot.id"), nullable=True
    )
    topic_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("topic_idea.id"), nullable=True
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(String(50), nullable=False, default="GENERAL")
    importance: Mapped[str] = mapped_column(String(20), nullable=False, default="SUPPORTING")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="UNVERIFIED")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    verifier_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )

    topic: Mapped[TopicIdea | None] = relationship("TopicIdea", back_populates="claims")
    source: Mapped[SourceSnapshot | None] = relationship("SourceSnapshot", back_populates="claims")


class ScriptDraft(Base):
    __tablename__ = "script_draft"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    topic_id: Mapped[str] = mapped_column(String(36), ForeignKey("topic_idea.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    target_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    voiceover_full_text: Mapped[str] = mapped_column(Text, nullable=False)
    scenes_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    claim_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    unverified_claim_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )

    topic: Mapped[TopicIdea] = relationship("TopicIdea", back_populates="scripts")
    hooks: Mapped[list[HookOption]] = relationship("HookOption", back_populates="script")


class HookOption(Base):
    __tablename__ = "hook_option"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    script_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("script_draft.id"), nullable=False
    )
    hook_text: Mapped[str] = mapped_column(Text, nullable=False)
    hook_technique: Mapped[str] = mapped_column(String(50), nullable=False, default="CURIOSITY_GAP")
    retention_score_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=7.0)
    is_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)

    script: Mapped[ScriptDraft] = relationship("ScriptDraft", back_populates="hooks")
