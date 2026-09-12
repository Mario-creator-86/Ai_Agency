"""Phase 4 SQLAlchemy declarative models for Factual Intelligence."""

from __future__ import annotations

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
)
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
    #: The runbook's six criteria as the proposer scored them, plus their mean as "composite".
    #: A score is an opinion about a candidate, never evidence about the world.
    scores_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: Authorised hosts the proposer expects to find evidence on. Retrieval still has to fetch.
    source_plan_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: Why this video should exist (migration 0032): the core fact, why now, why the audience
    #: should care, the payoff, a hook, an ending, a call to action, the risk, the length. A
    #: score is an opinion about a candidate; this is the argument it rests on.
    thesis_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #: The editorial rules this idea failed, if any. An idea the studio refused is kept with
    #: its reasons, because what was turned down is also what the studio learns from.
    rejection_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    #: Where this candidate stands in the company backlog, and why (migration 0033). Higher
    #: first. The Director reorders; the reason is what the Owner reads.
    priority: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    priority_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_by_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent.id", name="fk_topic_idea_proposed_by"), nullable=True
    )
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # Who did each half of the work. Independence between them is a requirement
    # (../architecture/02_SRS.md FR-038), and it can only be enforced if it is recorded.
    # NULL means no agent: an older claim, or one the Owner judged themselves.
    extracted_by_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent.id"), nullable=True
    )
    verified_by_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent.id"), nullable=True
    )
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
    #: The story this script tells (migration 0032): one message, the viewer's takeaway, the
    #: hook, the ending, the call to action and its kind, the structure, and the narration
    #: length estimated at the studio's measured speaking rate.
    story_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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


class StoryReview(Base):
    """The review that happens before anything is generated (migration 0032).

    Quality control measured the file, the voice artist checked pronunciation, the factual
    gate checked attribution — and nobody asked whether the thing was worth watching until
    after it had been paid for. This is that question, asked while the answer is still text:
    does the opening earn the next three seconds, does every sentence advance the story, is
    there a payoff that answers the hook, can the narration be said in the target length, and
    where would a viewer stop watching. It is cheaper to rewrite text than to buy a shot.
    """

    __tablename__ = "story_review"
    __table_args__ = (
        CheckConstraint("verdict IN ('PASS','REVISE','REJECT')", name="ck_story_review_verdict"),
        Index("ix_story_review_script", "script_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    script_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("script_draft.id"), nullable=False
    )
    verdict: Mapped[str] = mapped_column(String(10), nullable=False)
    checks_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    retention_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scores_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    notes_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    estimated_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reviewer_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent.id"), nullable=True
    )
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent_run.id"), nullable=True
    )
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )
