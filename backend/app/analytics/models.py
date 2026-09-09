"""Phase 7 SQLAlchemy declarative ORM models for Analytics and Learning Loop."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base
from app.publishing.models import ChannelRecord, PublicationRecord


class AnalyticsSnapshot(Base):
    """Time-series observation snapshot of an individual published video."""

    __tablename__ = "analytics_snapshot"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    publication_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("publication_record.id"), nullable=False
    )
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channel_record.id"), nullable=False
    )
    # 1h | 24h | 7d | 28d | LIFETIME
    window: Mapped[str] = mapped_column(String(20), nullable=False, default="LIFETIME")
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    watch_time_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    average_view_percentage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ctr_percentage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    likes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    shares: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subscribers_gained: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subscribers_lost: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    snapshot_at: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )

    publication: Mapped[PublicationRecord] = relationship("PublicationRecord")
    channel: Mapped[ChannelRecord] = relationship("ChannelRecord")


class ContentExperiment(Base):
    """Controlled A/B editorial experiment tracking variants and outcomes."""

    __tablename__ = "content_experiment"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channel_record.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    # RETENTION_RATE | CTR | COMPLETION_RATE
    target_metric: Mapped[str] = mapped_column(String(50), nullable=False, default="RETENTION_RATE")
    guardrail_metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # DRAFT | ACTIVE | CONCLUDED | CANCELLED
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    control_variant: Mapped[str] = mapped_column(String(100), nullable=False)
    treatment_variant: Mapped[str] = mapped_column(String(100), nullable=False)
    sample_size_target: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    control_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    treatment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    outcome_decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[str] = mapped_column(String(40), nullable=False)
    concluded_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )

    channel: Mapped[ChannelRecord] = relationship("ChannelRecord")


class ContentStrategy(Base):
    """Channel editorial strategy version with topic and hook technique weights."""

    __tablename__ = "content_strategy"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channel_record.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    topic_weights_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    hook_weights_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    target_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=45)
    cooldown_until: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )

    channel: Mapped[ChannelRecord] = relationship("ChannelRecord")


class DirectorRecommendation(Base):
    """Actionable editorial recommendation generated from cohort performance data."""

    __tablename__ = "director_recommendation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channel_record.id"), nullable=False
    )
    strategy_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("content_strategy.id"), nullable=True
    )
    # BOOST_TOPIC | REDUCE_TOPIC | FAVOR_HOOK | ADJUST_DURATION
    recommendation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_entity: Mapped[str] = mapped_column(String(100), nullable=False)
    # Bounded between -0.20 and +0.20
    suggested_weight_change: Mapped[float] = mapped_column(Float, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)  # N >= 3
    mean_retention: Mapped[float] = mapped_column(Float, nullable=False)
    mean_ctr: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_summary: Mapped[str] = mapped_column(Text, nullable=False)
    # PROPOSED | APPLIED | DISMISSED
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PROPOSED")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)

    strategy: Mapped[ContentStrategy | None] = relationship("ContentStrategy")
    channel: Mapped[ChannelRecord] = relationship("ChannelRecord")
